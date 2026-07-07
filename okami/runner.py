"""Runner — roda uma tarefa no harness montando tudo (memória, skills, MCP, learning).

Compartilhado entre a CLI (`okami task`) e o gateway (Telegram §13). Não imprime nada: recebe
`approve` (go/no-go), `on_event` (progresso) e `emit` (logs) como callbacks. Devolve a Task.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from okami import learning
from okami.llm import providers as prov
from okami import skills as skillmod
from okami.config import OkamiConfig
from okami.core import Budget, Harness, Task
from okami.core import default_registry
from okami.memory import files as memfiles
from okami.memory import make_embedder, open_memory
from okami.skills.skill_security import scan_path


def _should_review(ws, interval: int, clean: bool) -> bool:
    """Incrementa o contador de turnos LIMPOS em .okami/learning.json e diz se é hora do review (a cada
    `interval`). Só conclusão limpa conta (Hermes: final_response and not interrupted)."""
    import json as _json
    if interval <= 0 or not clean:
        return False
    p = Path(ws) / ".okami" / "learning.json"
    try:
        st = _json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        st = {}
    n = int(st.get("turns_since_review", 0)) + 1
    fire = n >= interval
    st["turns_since_review"] = 0 if fire else n
    try:
        from okami.core.safe_io import write_atomic
        write_atomic(p, _json.dumps(st))               # atômico: crash no meio não corrompe o contador de review
    except OSError:
        pass
    return fire


def _maybe_background_review(cfg, ws, task, *, skills_dir, model, provider, emit, notify=None,
                            core_block=None) -> None:
    """Auto-aprimoramento MODEL-DRIVEN (estilo Hermes): a cada N turnos LIMPOS, forka um review isolado
    que decide (via tools) o que vale salvar. Roda em background (não bloqueia o turno do usuário).
    Se `notify` (canal ao dono), AVISA o que foi aprendido — transparência (#9)."""
    from okami.core import TaskState
    lc = cfg.learning or {}
    if not lc.get("review", True):
        return
    if not _should_review(ws, int(lc.get("review_interval", 6)), task.state == TaskState.COMPLETE):
        return
    from okami.learning.review import learned_summary, run_review, summarize_turn
    ctx = summarize_turn(task)

    def _bg():
        from okami.llm.aux import aux_for
        aux_p, aux_m = aux_for(cfg, "review")        # fundo → modelo auxiliar barato (Hermes: −85% custo)
        rt = run_review(cfg, ws, ctx, skills_dir=skills_dir,
                        model=aux_m or model, provider=aux_p or provider, emit=lambda m: None,
                        core_block=core_block)         # #10: reusa a identidade/memória do pai (prefix-cache)
        if notify is not None and rt is not None:    # #9: avisa o dono do que aprendeu (se algo foi salvo)
            msg = learned_summary(getattr(rt, "result", None))
            if msg:
                try:
                    notify(msg)
                except Exception as e:  # noqa: BLE001 — aviso é best-effort, mas a falha NÃO é silenciosa
                    emit(f"⚠ não consegui avisar o dono do que aprendi (o aprendizado FOI salvo): {e}")
    if lc.get("review_sync"):              # síncrono (testes / CLI one-shot que sai rápido)
        _bg()
    else:                                 # background: roda DEPOIS de a pessoa já ter a resposta
        import threading
        threading.Thread(target=_bg, daemon=True).start()


def _overall_timeout_for(cfg) -> float:
    """Teto GLOBAL de tempo da fase de geração (item 3). OKAMI_OVERALL_TIMEOUT > cfg.harness.overall_timeout
    > 300s. 0/negativo desliga. Protege o gateway da cascata retry×fallback pendurar o canal por minutos."""
    import os
    env = os.environ.get("OKAMI_OVERALL_TIMEOUT")
    if env:
        try:
            return max(0.0, float(env))
        except ValueError:
            pass
    h = getattr(cfg, "harness", None) or {}
    v = h.get("overall_timeout") if isinstance(h, dict) else getattr(h, "overall_timeout", None)
    try:
        return float(v) if v is not None else 300.0
    except (TypeError, ValueError):
        return 300.0


def _run_with_deadline(fn, timeout):
    """Roda `fn` com teto de relógio: devolve o resultado, ou levanta TimeoutError se passar de `timeout`
    (a chamada em voo é ABANDONADA numa thread daemon — ela morre sozinha no próprio timeout de 150s). O
    loop classifica o TimeoutError → encolhe o contexto + re-gera → salvage. 0/None = sem teto."""
    if not timeout or timeout <= 0:
        return fn()
    import threading
    box: dict = {}

    def _worker():
        try:
            box["r"] = fn()
        except BaseException as e:  # noqa: BLE001 — propaga o erro interno pro chamador
            box["e"] = e
    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError(f"geração excedeu o teto global de {int(timeout)}s — abortando a cascata de retry")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def _native_tools_for(pc, registry, eff_dict):
    """Injeta no payload as tools do registry JÁ FILTRADO (surface/disponibilidade) quando o provider faz
    function-calling nativo — usado em TODO caminho de geração (generate E escalate). Sem isto, o caminho
    de ESCALADA mandava o default inteiro (ou nada): na superfície Telegram o modelo recebia run_shell/spawn
    (negados) e os chamava → 'ferramenta inválida'. Idempotente: não sobrescreve `tools` já passadas."""
    if not registry or pc is None or "tools" in eff_dict:
        return eff_dict
    try:
        from okami.llm.native_capability import native_supported
        if native_supported(pc):
            from okami.core.tools import openai_tools
            eff_dict["tools"] = openai_tools(registry)
    except Exception:  # noqa: BLE001 — qualquer pepino → provider cai no default (comportamento antigo)
        pass
    return eff_dict


def run_task(
    cfg: OkamiConfig,
    workspace,
    goal: str,
    *,
    exit_criteria: list[dict] | None = None,
    provider: str | None = None,
    model: str | None = None,
    approve: Callable[[dict], bool] | None = None,
    on_event: Callable[[dict], None] | None = None,
    max_steps: int | None = None,            # None → harness.max_steps do okami.yaml (default 200)
    escalate_to: str | None = None,
    skills_dir: str | None = None,           # None → casa central (okami.home.skills_dir): não espalha
    extra_context: str = "",
    cancel: Callable[[], bool] | None = None,
    notify: Callable[[str], object] | None = None,   # entrega FORA-DO-TURNO ao dono (#7 item 3): o gateway
                                                     # injeta; o harness "toca" o dono no meio da tarefa
                                                     # (vigia/loop/lembrete). None = sem canal (CLI puro).
    clarify: Callable[[str, list], object] | None = None,  # PERGUNTA bloqueante ao dono (#8 item 1); o gateway
                                                     # injeta. None = sem dono interativo → tool falha em paz.
    depth: int = 0,
    images: list[str] | None = None,
    reasoning_effort: str | None = None,     # esforço de raciocínio p/ esta tarefa (/think) — vence o default
    native_override: str | None = None,      # /native-tools: "on"/"off" força o rail; vazio/None = smart default
    prelearned_files: list[str] | None = None,  # arquivos já "conhecidos" (não exige read antes de sobrescrever)
    surface: str = "cli",                        # superfície (cli/telegram/group/paperclip/subagent) → tool policy
    chat_id: str = "",                           # #2: chat de origem → carimba no process_start p/ notificar o chat certo
    registry_filter: set[str] | None = None,     # allowlist de tools (None=todas) — review usa o conjunto seguro
    learn: bool = True,                          # False → pula o review pós-turno (sem recursão no próprio review)
    agent_home: str | Path | None = None,        # CASA do agente (identidade/memória/sessões/learning) — se
                                                 # None, = workspace (retrocompat). Separa "onde mora o agente"
                                                 # de "onde ele mexe em arquivos" (workspace=projeto/CWD).
    open_fs: bool = False,                        # DONO no CLI: agente alcança TODO o FS (relativo no CWD,
                                                 # absoluto livre). Telegram/grupo = False (jail do workspace).
    allow_paths: list | None = None,             # pastas extras liberadas além do workspace (config tools.allow_paths)
    remote=None,                                 # alvo de execução REMOTO (RemoteTarget) — FS/shell rodam LÁ
    set_remote=None,                             # hook p/ persistir o alvo remoto na sessão (sobrevive ao turno)
    core_block: str | None = None,               # #10: identidade/memória JÁ renderizada (review reusa a do pai →
                                                 # prefixo byte-idêntico = prefix-cache + pula a re-leitura do disco)
    emit: Callable[[str], None] = lambda m: None,
) -> Task:
    ws = Path(workspace)                          # operacional: jail de arquivos, shell, find, @refs
    ws.mkdir(parents=True, exist_ok=True)
    home = Path(agent_home) if agent_home else ws  # casa: memória/identidade/taste/learning (ISOLADA do projeto)
    home.mkdir(parents=True, exist_ok=True)
    if skills_dir is None:                    # casa central (projeto/okami.yaml ou ~/.okami) — não o CWD cru
        from okami.home import skills_dir as _skills_home
        skills_dir = str(_skills_home())

    from okami.integrations.references import expand_references          # @file / @url / @gitdiff (#3)
    goal, ref_block = expand_references(goal, ws)
    if ref_block:
        extra_context = (ref_block + "\n\n" + extra_context) if extra_context else ref_block

    # Vision (§6): só manda imagem p/ modelo multimodal — flag explícita OU catálogo de capacidade
    # (gpt-4o/5.x, claude, gemini… já passam sem configurar capability.vision na mão).
    from okami.llm.model_catalog import model_vision
    _pc_v = cfg.provider(provider)
    if images and not (_pc_v.capability.vision or model_vision(model or _pc_v.model)):
        emit("modelo atual sem visão — imagem ignorada (configure capability.vision: true num provider).")
        extra_context = "[O usuário enviou imagem(ns), mas este modelo não tem visão.]\n\n" + extra_context
        images = None

    def _spawn(subgoal, agent=None, model_=None, on_event=None):  # subagente em runtime (#1), guarda de profundidade
        if depth >= 2:
            return "(limite de profundidade de subagentes atingido)"
        scfg, sws, shome = cfg, ws, home
        if agent:
            from okami.agents import effective_config, load_agents
            from okami.config import load_raw
            spec = load_agents().get(agent)
            if spec:
                graw, _ = load_raw()
                scfg, sws, shome = effective_config(graw, spec), spec.dir, spec.dir
        sub = run_task(scfg, sws, subgoal, model=model_, max_steps=12, depth=depth + 1,
                       agent_home=shome, open_fs=open_fs, allow_paths=allow_paths,   # herda acesso amplo
                       surface="subagent", emit=emit, on_event=on_event)   # #6: progresso do bg spawn
        return (sub.result or sub.reason or sub.state.value)[:2000]

    eff = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
    from okami.llm.usage import CanonicalUsage
    _acc = {"usage": CanonicalUsage(), "served": ""}   # tokens + quem respondeu (custo §A5 / served-by §E5)

    from okami.llm.streaming import streaming_enabled as _stream_on
    _streaming = _stream_on(cfg, provider)   # MESMO provider selecionado p/ esta task (-p/--provider), não o default

    _deadline = _overall_timeout_for(cfg)              # #3: teto global da fase de geração

    try:                                               # chars/token p/ ESTIMAR tokens quando o provider local
        _cpt = float(cfg.provider(provider).chars_per_token) if cfg else 4.0   # (LMStudio) não reporta usage
    except Exception:  # noqa: BLE001
        _cpt = 4.0

    def _fill_usage(res, messages):
        """Modelo local não devolve usage → estima por chars (marcado ~) p/ o dono SEMPRE ver tokens."""
        if res is not None and res.usage.total_tokens == 0:
            from okami.llm.usage import estimate_usage
            _in = "".join(str((m or {}).get("content", "")) for m in (messages or []) if isinstance(m, dict))
            res.usage = estimate_usage(_in, getattr(res, "text", "") or "", chars_per_token=_cpt)
        return res

    # heartbeat best-effort durante backoff de retry: mantém o status 'ainda trabalhando' vivo (o heartbeat
    # normal só roda ENTRE passos; um backoff longo é UM passo bloqueado). Sem on_event → no-op.
    _retry_hb = (lambda: on_event({"type": "retry_wait"})) if on_event else None

    def generate(messages, schema=None, on_token=None, max_tokens=None):
        eff2 = dict(eff)
        if max_tokens:                      # boost de length (harness pede mais espaço p/ a continuação fechar)
            eff2["max_tokens"] = int(max_tokens)
        _native_tools_for(cfg.provider(provider), registry, eff2)   # NATIVO: SÓ o registry FILTRADO (não o
        #                                    default inteiro) — senão tool podada → "ferramenta inválida"

        def _call():
            if on_token and _streaming:     # #16: streaming token-a-token (protocolo de texto)
                from okami.llm.streaming import streaming_generate
                return streaming_generate(cfg, messages, provider=provider, model=model,
                                          response_schema=schema, on_token=on_token, **eff2)
            return prov.complete_messages_ex(cfg, messages, provider=provider, model=model,
                                             response_schema=schema, cancel=cancel,   # /stop corta o backoff;
                                             on_heartbeat=_retry_hb, **eff2)            # status vivo no backoff
        res = _run_with_deadline(_call, _deadline)     # #3: aborta a cascata se passar do teto
        _fill_usage(res, messages)                     # usage zerado (local) → estima por chars (~)
        _acc["usage"] = _acc["usage"] + res.usage
        if res.provider:
            _acc["served"] = f"{res.provider}/{res.model}".rstrip("/")
        return res                      # Completion INTEIRO (tool_calls/finish_reason) → harness (P0.4)

    escalate = None
    if escalate_to:
        def escalate(messages, schema=None):  # noqa: F811
            eff_esc = _native_tools_for(cfg.provider(escalate_to), registry, dict(eff))  # MESMO registry
            #                                FILTRADO da geração normal (senão Telegram recebia run_shell/spawn)
            res = prov.complete_messages_ex(cfg, messages, provider=escalate_to, response_schema=schema,
                                            cancel=cancel, on_heartbeat=_retry_hb, **eff_esc)
            _fill_usage(res, messages)                  # idem: estima se o provider não reportar
            _acc["usage"] = _acc["usage"] + res.usage
            if res.provider:
                _acc["served"] = f"{res.provider}/{res.model}".rstrip("/")
            return res                      # Completion inteiro (P0.4)

    # Skills: forçadas por contrato (inteiras) + catálogo (use_skill). Descarta bloqueadas pelo scan.
    # with_builtin junta as NATIVAS do pacote (viajam no install); a skill do usuário vence por nome.
    all_skills = skillmod.with_builtin(skillmod.load_skills(Path(skills_dir)))
    safe = [s for s in all_skills if not scan_path(s.path.parent).blocked]
    import sys as _sys                                  # #11: gating do CATÁLOGO por plataforma/ambiente —
    safe = skillmod.visible_skills(safe, os_name=_sys.platform, active_environments=None)  # esconde skill de
    #   OS/runtime irrelevante do índice (load explícito por nome ainda resolve)
    if len(safe) != len(all_skills):
        emit("skills bloqueadas pelo scan: " + ", ".join({s.name for s in all_skills} - {s.name for s in safe}))
    routed = skillmod.route(goal, cfg.contracts, safe)
    # Embedder construído UMA vez (probe único) e reaproveitado: ranqueia o catálogo de skills por
    # INTENÇÃO E alimenta a memória. Sem embedder remoto → o catálogo cai no HRR local (offline).
    embedder = make_embedder(cfg.memory.get("embedder"))
    catalog = skillmod.catalog(safe, exclude={s.name for s in routed}, goal=goal, embedder=embedder)
    # Taste model (§9): em tarefa de UI, injeta o GOSTO aprendido (crítico soft) junto às skills.
    from okami.learning import taste as tastemod
    ui_task = bool((cfg.contracts or {}).get("ui")) or any(
        k in s.name.lower() for s in routed for k in ("frontend", "design", "shadcn", "heroui", "ui"))
    taste_block = tastemod.TasteProfile.load(home).steer() if ui_task else ""
    # Persona Compiler (#8): direção CURTA do turno (registro técnico em papo + estado emocional),
    # read-only — a identidade inteira segue indo via core_block. Vazio quando não há sinal.
    from okami.learning.compiler import compile_turn
    turn_steer = compile_turn(goal, exit_criteria, contracts=cfg.contracts)
    # #10 env_probe: avisa o MODELO se o ambiente Python local está torto (pip/PEP-668) — silencioso
    # quando saudável; só local (no remoto o python é outro, roda lá).
    env_hint = ""
    if remote is None:
        try:
            from okami.core.env_probe import probe_python_env
            env_hint = probe_python_env()
        except Exception:  # noqa: BLE001 — sonda é best-effort
            env_hint = ""
    # turn_steer primeiro (direção base); extra_context (com overlay de sessão) pode sobrepor depois.
    system_extra = "\n\n".join(x for x in (turn_steer, extra_context, taste_block,
                                           skillmod.render_block(routed), catalog, env_hint) if x)
    skills_map = {}
    for s in safe:                                    # nome canônico + aliases antigos → use_skill resolve os dois
        skills_map[s.name] = s.body
        for a in s.aliases:
            skills_map.setdefault(a, s.body)

    mem = open_memory(home, backend=cfg.memory.get("backend", "sqlite-fts5"),
                      embedder=embedder, config=cfg.memory)
    # #10: o review reusa a identidade/memória JÁ renderizada do pai (prefixo byte-idêntico p/ o
    # prefix-cache + pula a re-leitura do disco). None = renderiza do disco (caminho normal).
    core_block = core_block if core_block is not None else memfiles.core_block(home, cfg.memory.get("files", {}))

    from okami.core.tool_policy import filter_registry, prune_unavailable
    registry = filter_registry(default_registry(), surface, config=getattr(cfg, "tools", None),
                               sandbox=getattr(cfg, "sandbox", None))   # #P1: gate de isolamento no worker
    registry = prune_unavailable(registry, emit=emit)   # check_fn (item 27): dep/credencial faltando → sai
    mcp_clients = []
    servers = (cfg.mcp or {}).get("servers")
    if servers:
        from okami.core.tool_policy import filter_mcp_registry
        from okami.integrations.mcp import load_mcp_tools
        mcp_tools, mcp_clients = load_mcp_tools(servers, emit=emit)
        # #P1: MCP entra DEPOIS do filtro por surface → reaplica a policy (capability × superfície).
        # Sem isto, uma tool MCP write/shell/network escapava da postura remota e furava o sandbox.
        mcp_tools = filter_mcp_registry(mcp_tools, surface, config=getattr(cfg, "tools", None),
                                        sandbox=getattr(cfg, "sandbox", None), emit=emit)
        registry.update(mcp_tools)
    # Plugins (paridade Hermes): cada plugin roda `register(ctx)` e pode CONTRIBUIR tools. Igual ao MCP, entram
    # DEPOIS do filtro por superfície → reaplica a tool-policy (capability × surface × sandbox) e NÃO podem
    # sombrear uma tool NATIVA/MCP de mesmo nome (core vence — um plugin de pasta não sequestra `run_shell`).
    try:
        from okami.plugins import discover_plugins, load_plugin_tools, plugin_roots
        ptools = load_plugin_tools(discover_plugins(plugin_roots()), cfg=cfg, emit=emit)
        if ptools:
            from okami.core.tool_policy import filter_mcp_registry
            ptools = filter_mcp_registry(ptools, surface, config=getattr(cfg, "tools", None),
                                         sandbox=getattr(cfg, "sandbox", None), emit=emit)
            for _nm, _tool in ptools.items():
                if _nm not in registry:                  # core/MCP vencem: plugin não sombreia tool existente
                    registry[_nm] = _tool
    except Exception:  # noqa: BLE001 — plugin quebrado não derruba o boot do agente
        from okami.log import warn
        warn("falha ao carregar tools de plugins", exc_info=True)
    if registry_filter is not None:                  # review: restringe ao conjunto seguro (memória/skill)
        registry = {k: v for k, v in registry.items() if k in registry_filter}

    # Auto-compaction adaptativa à janela do modelo (§6.4): Qwen 32K comprime cedo, Claude 200K tarde.
    pc = cfg.provider(provider)
    if native_override in ("on", "off"):                  # /native-tools desta sessão → cópia (não muta o
        pc = pc.model_copy(update={"native_tools": native_override == "on"})   # provider compartilhado)
    tune_key = model or pc.name
    if (cfg.learning or {}).get("auto_tune"):         # §7: aplica calibração aprendida do modelo
        ov = learning.tuned_overrides(ws, tune_key)
        if ov.get("tool_mode") and pc.capability.tool_mode != ov["tool_mode"]:
            pc.capability.tool_mode = ov["tool_mode"]
            emit(f"🔧 auto-tune: {tune_key} → tool_mode={ov['tool_mode']}")
    if max_steps is None:                    # tunável no okami.yaml: harness.max_steps (default 200)
        max_steps = int((getattr(cfg, "harness", None) or {}).get("max_steps", 200))
    # anti-travamento (NÃO teto de turno): tempo máx. sem concluir passo. Tunável: harness.max_stall_seconds.
    _stall = float((getattr(cfg, "harness", None) or {}).get("max_stall_seconds", 300.0))
    from okami.core.harness.loopguard_config import guardrail_budget_overrides
    budget = Budget(max_steps=max_steps, max_stall_seconds=_stall,
                    max_context_chars=prov.compaction_threshold_chars(pc),
                    **guardrail_budget_overrides(cfg))   # #11: tools.loop_guardrails afina os thresholds
    emit(f"janela≈{prov.context_window_tokens(pc)//1000}K tokens · compacta em ~{budget.max_context_chars//1000}k chars")

    from okami.gateway.checkpoints import Checkpoints
    from okami.automation.hooks import HookManager
    hooks = HookManager(cfg.hooks, root=str(ws), emit=emit, include_builtin=True)   # event hooks (§11) + nativos
    t = Task(goal=goal, exit_criteria=exit_criteria or [])
    if not hooks.fire("before_task", {"goal": goal}):         # política externa pode VETAR a tarefa
        from okami.core import TaskState
        t.state, t.reason = TaskState.BLOCKED, "bloqueada por hook before_task"
        mem.close()
        for c in mcp_clients:
            c.close()
        return t
    from okami.core.sandbox import effective_sandbox
    sandbox = effective_sandbox(cfg.sandbox, surface)   # #P1.1: superfície exposta endurece por padrão
    from okami.llm.native_capability import native_supported
    _native = native_supported(pc)   # provider honra function-calling? (False instantâneo se native_tools off)
    _hkw = dict(
        budget=budget, stream_tokens=_streaming, native_tools=_native,
        on_event=on_event, escalate=escalate, system_extra=system_extra,
        memory=mem, core_block=core_block, approve=approve,
        skills=skills_map, registry=registry, cancel=cancel,
        checkpoints=Checkpoints(ws), hooks=hooks, spawn=_spawn,   # snapshot + hooks + subagente
        images=images, prelearned_files=prelearned_files,   # vision §6 + arquivos pré-conhecidos
        sandbox=sandbox, skills_dir=skills_dir, open_fs=open_fs, surface=surface, chat_id=chat_id,
        model=model or pc.model, allow_paths=allow_paths,
        agent_home=home,              # memória/identidade escrevem na CASA, não no CWD
        cfg=cfg,                      # tools que roteiam ao modelo auxiliar (web_extract/vision)
        # write_approval: escrita AUTOMÁTICA (review em background) vai pra fila do dono
        stage_writes=(surface == "review" and bool((cfg.memory or {}).get("write_approval"))),
    )
    if notify is not None:            # entrega FORA-DO-TURNO ao dono (#7 item 3) — só passa quando há canal
        _hkw["notify"] = notify
    if clarify is not None:           # PERGUNTA bloqueante ao dono (#8 item 1) — só passa quando há dono interativo
        _hkw["clarify"] = clarify
    if remote is not None:            # ambiente remoto (SSH/Tailscale): FS/shell rodam no host
        _hkw["remote"] = remote
    if set_remote is not None:        # persiste o alvo na sessão (sobrevive ao turno)
        _hkw["set_remote"] = set_remote
    try:
        harness = Harness(generate, t, ws, **_hkw)
    except TypeError:                 # ctor ainda sem `notify`/`clarify` (landing paralelo) → fail-open
        _hkw.pop("notify", None)
        _hkw.pop("clarify", None)
        harness = Harness(generate, t, ws, **_hkw)
    try:
        harness.run()
        t.stats["usage"] = _acc["usage"].to_dict()        # tokens do turno (custo §A5)
        t.stats["served_by"] = _acc["served"]             # quem realmente respondeu (§E5)
        hooks.fire("after_task", {"goal": goal, "state": t.state.value, "result": t.result or ""})
        if learn:                                        # review (learn=False) não despeja seu prompt sintético
            from okami.memory import save_turn            # P2: save_messages (default OFF) alimenta a memória
            save_turn(mem, goal, source="user", cfg_memory=cfg.memory)       # conversa bruta (Honcho user-model)
            save_turn(mem, t.result or "", source="agent", cfg_memory=cfg.memory)
        if learn:
            try:
                learning.apply(mem, t, model_name=model or "default")   # anti-padrão GENERALIZADO só em falha real
                if (cfg.memory or {}).get("auto_consolidate", True):    # consolidação heurística pós-tarefa
                    mem.consolidate()                          # expira TTL + funde quase-duplicatas (sem LLM)
                learning.record_run(ws, tune_key, t.stats)     # §7: acumula stats p/ auto-tune do modelo
                # Auto-aprimoramento MODEL-DRIVEN (estilo Hermes): o modelo decide o que salvar via tools,
                # guiado pela lista "Do NOT capture", a cada N turnos e SÓ em conclusão limpa. Substitui a
                # destilação MECÂNICA (que gerava lixo). auto_skill mecânico fica como legado opt-in.
                _maybe_background_review(cfg, home, t, skills_dir=skills_dir, model=model, provider=provider,
                                         emit=emit, notify=notify,    # #9: avisa o dono do que aprendeu
                                         core_block=core_block)       # #10: review reusa a identidade do pai
                if (cfg.learning or {}).get("auto_skill"):     # opt-in: destilação pós-tarefa (LLM-ou-nada,
                    name = learning.maybe_write_skill(t, skills_dir=skills_dir, model_name=model or "default", cfg=cfg)
                    if name:                                   # julgamento worth + gate determinístico)
                        emit(f"🧠 skill destilada: {name}")
            except Exception as e:  # noqa: BLE001 — aprendizado é best-effort, mas a falha NÃO é silenciosa
                from okami.core.redact import redact
                emit(f"⚠ aprendizado/memória pós-tarefa falhou (não afeta a resposta): {redact(str(e))[:160]}")
    finally:
        mem.close()
        for c in mcp_clients:
            c.close()
    return t
