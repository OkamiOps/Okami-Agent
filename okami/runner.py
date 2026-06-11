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
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_json.dumps(st), encoding="utf-8")
    except OSError:
        pass
    return fire


def _maybe_background_review(cfg, ws, task, *, skills_dir, model, provider, emit) -> None:
    """Auto-aprimoramento MODEL-DRIVEN (estilo Hermes): a cada N turnos LIMPOS, forka um review isolado
    que decide (via tools) o que vale salvar. Roda em background (não bloqueia o turno do usuário)."""
    from okami.core import TaskState
    lc = cfg.learning or {}
    if not lc.get("review", True):
        return
    if not _should_review(ws, int(lc.get("review_interval", 6)), task.state == TaskState.COMPLETE):
        return
    from okami.learning.review import run_review, summarize_turn
    ctx = summarize_turn(task)

    def _bg():
        run_review(cfg, ws, ctx, skills_dir=skills_dir, model=model, provider=provider, emit=lambda m: None)
    if lc.get("review_sync"):              # síncrono (testes / CLI one-shot que sai rápido)
        _bg()
    else:                                 # background: roda DEPOIS de a pessoa já ter a resposta
        import threading
        threading.Thread(target=_bg, daemon=True).start()


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
    depth: int = 0,
    images: list[str] | None = None,
    reasoning_effort: str | None = None,     # esforço de raciocínio p/ esta tarefa (/think) — vence o default
    prelearned_files: list[str] | None = None,  # arquivos já "conhecidos" (não exige read antes de sobrescrever)
    surface: str = "cli",                        # superfície (cli/telegram/group/paperclip/subagent) → tool policy
    registry_filter: set[str] | None = None,     # allowlist de tools (None=todas) — review usa o conjunto seguro
    learn: bool = True,                          # False → pula o review pós-turno (sem recursão no próprio review)
    agent_home: str | Path | None = None,        # CASA do agente (identidade/memória/sessões/learning) — se
                                                 # None, = workspace (retrocompat). Separa "onde mora o agente"
                                                 # de "onde ele mexe em arquivos" (workspace=projeto/CWD).
    open_fs: bool = False,                        # DONO no CLI: agente alcança TODO o FS (relativo no CWD,
                                                 # absoluto livre). Telegram/grupo = False (jail do workspace).
    allow_paths: list | None = None,             # pastas extras liberadas além do workspace (config tools.allow_paths)
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

    def _spawn(subgoal, agent=None, model_=None):     # subagente em runtime (#1), com guarda de profundidade
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
                       surface="subagent", emit=emit)   # subagente: surface restrita (não spawna de novo)
        return (sub.result or sub.reason or sub.state.value)[:2000]

    eff = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
    from okami.llm.usage import CanonicalUsage
    _acc = {"usage": CanonicalUsage(), "served": ""}   # tokens + quem respondeu (custo §A5 / served-by §E5)

    def generate(messages, schema=None):
        res = prov.complete_messages_ex(cfg, messages, provider=provider, model=model,
                                        response_schema=schema, **eff)
        _acc["usage"] = _acc["usage"] + res.usage
        if res.provider:
            _acc["served"] = f"{res.provider}/{res.model}".rstrip("/")
        return res                      # Completion INTEIRO (tool_calls/finish_reason) → harness (P0.4)

    escalate = None
    if escalate_to:
        def escalate(messages, schema=None):  # noqa: F811
            res = prov.complete_messages_ex(cfg, messages, provider=escalate_to, response_schema=schema, **eff)
            _acc["usage"] = _acc["usage"] + res.usage
            if res.provider:
                _acc["served"] = f"{res.provider}/{res.model}".rstrip("/")
            return res                      # Completion inteiro (P0.4)

    # Skills: forçadas por contrato (inteiras) + catálogo (use_skill). Descarta bloqueadas pelo scan.
    all_skills = skillmod.load_skills(Path(skills_dir))
    safe = [s for s in all_skills if not scan_path(s.path.parent).blocked]
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
    # turn_steer primeiro (direção base); extra_context (com overlay de sessão) pode sobrepor depois.
    system_extra = "\n\n".join(x for x in (turn_steer, extra_context, taste_block,
                                           skillmod.render_block(routed), catalog) if x)
    skills_map = {}
    for s in safe:                                    # nome canônico + aliases antigos → use_skill resolve os dois
        skills_map[s.name] = s.body
        for a in s.aliases:
            skills_map.setdefault(a, s.body)

    mem = open_memory(home, backend=cfg.memory.get("backend", "sqlite-fts5"),
                      embedder=embedder, config=cfg.memory)
    core_block = memfiles.core_block(home, cfg.memory.get("files", {}))

    from okami.core.tool_policy import filter_registry
    registry = filter_registry(default_registry(), surface, config=getattr(cfg, "tools", None),
                               sandbox=getattr(cfg, "sandbox", None))   # #P1: gate de isolamento no worker
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
    if registry_filter is not None:                  # review: restringe ao conjunto seguro (memória/skill)
        registry = {k: v for k, v in registry.items() if k in registry_filter}

    # Auto-compaction adaptativa à janela do modelo (§6.4): Qwen 32K comprime cedo, Claude 200K tarde.
    pc = cfg.provider(provider)
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
    budget = Budget(max_steps=max_steps, max_stall_seconds=_stall,
                    max_context_chars=prov.compaction_threshold_chars(pc))
    emit(f"janela≈{prov.context_window_tokens(pc)//1000}K tokens · compacta em ~{budget.max_context_chars//1000}k chars")

    from okami.gateway.checkpoints import Checkpoints
    from okami.automation.hooks import HookManager
    hooks = HookManager(cfg.hooks, root=str(ws), emit=emit)   # event hooks (§11)
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
    harness = Harness(generate, t, ws, budget=budget,
                      on_event=on_event, escalate=escalate, system_extra=system_extra,
                      memory=mem, core_block=core_block, approve=approve,
                      skills=skills_map, registry=registry, cancel=cancel,
                      checkpoints=Checkpoints(ws), hooks=hooks, spawn=_spawn,   # snapshot + hooks + subagente
                      images=images, prelearned_files=prelearned_files,   # vision §6 + arquivos pré-conhecidos
                      sandbox=sandbox, skills_dir=skills_dir, open_fs=open_fs, surface=surface,
                      model=model or pc.model, allow_paths=allow_paths)
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
                _maybe_background_review(cfg, home, t, skills_dir=skills_dir, model=model, provider=provider, emit=emit)
                if (cfg.learning or {}).get("auto_skill"):     # opt-in: destilação pós-tarefa (LLM-ou-nada,
                    name = learning.maybe_write_skill(t, skills_dir=skills_dir, model_name=model or "default", cfg=cfg)
                    if name:                                   # julgamento worth + gate determinístico)
                        emit(f"🧠 skill destilada: {name}")
            except Exception:  # noqa: BLE001
                pass
    finally:
        mem.close()
        for c in mcp_clients:
            c.close()
    return t
