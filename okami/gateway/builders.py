"""Builders do gateway: monta AgentEndpoint/GroupEndpoint a partir da config, scheduler e run_gateway."""

from __future__ import annotations

import threading
import time
from typing import Callable

from okami.gateway.endpoint import AgentEndpoint
from okami.gateway.group import GroupEndpoint


def fs_access_from_tools(tools: dict) -> dict:
    """Resolve o ACESSO A ARQUIVOS do bloco `tools` num par (open_fs, allow_paths) — padrão de mercado
    (OpenClaw `workspaceOnly` / Hermes denylist): UM knob `tools.fs` em vez de listar pasta por pasta.

      tools.fs: workspace  (default) → só o workspace (jail; deny-by-default p/ Telegram)
      tools.fs: home                 → TUDO embaixo de ~/ (Documents, Pictures, Desktop, Downloads…)
      tools.fs: full                 → o filesystem inteiro (= open_fs)
    `tools.open_fs: true` segue valendo (alias de full). `tools.allow_paths` adiciona extras fora da
    home (ex.: /Volumes/x). Segredo (.env/.ssh/.aws) continua bloqueado pelo _SENSITIVE_PATH nos 3.

    NOTA: isto resolve só o ACESSO A ARQUIVOS. Shell/processo numa superfície REMOTA (Telegram) é
    deny-by-default por segurança — o dono libera com `tools.shell: true` (run_shell/execute_code/
    process_*) ou `tools.process`/`tools.spawn` (ver tool_policy._CAPABILITY_GRANTS). Aprovação/
    hardline/sandbox seguem valendo por cima."""
    from pathlib import Path
    tools = tools or {}
    mode = str(tools.get("fs", "workspace")).strip().lower()
    open_fs = bool(tools.get("open_fs", False)) or mode == "full"
    allow = list(tools.get("allow_paths") or [])
    if mode == "home":                                # ~/ inteiro liberado, sem listar subpastas
        allow = [str(Path.home()), *allow]
    return {"open_fs": open_fs, "allow_paths": allow}


def _endpoint_kwargs_from_cfg(cfg) -> dict:
    """Acesso a arquivos do endpoint a partir do bloco `tools` (ver fs_access_from_tools)."""
    return fs_access_from_tools(getattr(cfg, "tools", None) or {})


def build_group_endpoints(global_raw: dict, agents: dict, groups: list,
                          emit: Callable[[str], None] = lambda m: None,
                          make_channel=None) -> list["GroupEndpoint"]:
    """Um GroupEndpoint por grupo em okami.yaml (groups). Cada membro entra com a SUA token
    (channels.telegram.token do agent.yaml); o grupo precisa de ≥1 membro com token."""
    from okami.channels.telegram import TelegramGroupChannel
    from okami.config import build_config
    from okami.agents.group import agent_responder, build_room, llm_moderator

    eps: list[GroupEndpoint] = []
    for gi, gcfg in enumerate(groups or []):
        member_ids = [m for m in (gcfg.get("members") or []) if m in agents]
        tokens = {aid: ((agents[aid].raw.get("channels") or {}).get("telegram") or {}).get("token")
                  for aid in member_ids}
        tokens = {aid: t for aid, t in tokens.items() if t}
        if not tokens:
            emit(f"grupo {gi}: nenhum membro com channels.telegram.token — pulando")
            continue
        mod_provider = (gcfg.get("moderator") or {}).get("provider")
        room = build_room(global_raw, agents, gcfg,
                          select_speaker=llm_moderator(build_config(global_raw), provider=mod_provider),
                          respond=agent_responder(global_raw, agents))
        g_allow, g_all = gcfg.get("allow_chats"), bool(gcfg.get("allow_all", False))
        if not g_allow and not g_all:
            emit(f"⚠ [grupo{gi}] sem allowlist → deny-by-default. Configure allow_chats ou allow_all: true.")
        channel = (make_channel or TelegramGroupChannel)(tokens, allow_chats=g_allow, allow_all=g_all)
        eps.append(GroupEndpoint(room, channel, label=f"grupo{gi}",
                                 min_delay=float(gcfg.get("min_delay", 0.0)), emit=emit))
        emit(f"grupo {gi} no ar: {', '.join(tokens)} ({len(tokens)} bots) · moderador={mod_provider or 'default'}")
    return eps


def _build_channel(ctype: str, cc: dict):
    """Fábrica de canal não-Telegram (#15) — delega ao registry declarativo. KeyError se faltar campo."""
    from okami.gateway.channel_registry import build_channel
    return build_channel(ctype, cc)


def build_endpoints(global_raw: dict, agents: dict, emit: Callable[[str], None] = lambda m: None,
                    make_channel=None, run_task=None) -> list[AgentEndpoint]:
    from okami.agents import effective_config
    from okami.channels.telegram import TelegramChannel
    from okami.runner import run_task as _default_run_task

    run_task = run_task or _default_run_task

    def _mk_endpoint(aid, spec, cfg, channel) -> AgentEndpoint:
        # histórico da sessão ~12% da janela do modelo (32K Qwen guarda menos; 200K Claude mais).
        from okami.llm.providers import context_window_tokens
        from okami.voice import make_stt, make_tts
        pc = cfg.provider()
        hist_chars = max(2000, int(context_window_tokens(pc) * pc.chars_per_token * 0.12))
        voice = cfg.voice or {}
        gw = cfg.gateway or {}
        return AgentEndpoint(aid, cfg, spec.dir, channel, run_task=run_task,
                             approval_mode=(cfg.approvals or {}).get("mode", "manual"),
                             max_history_chars=hist_chars,
                             stt=make_stt(voice.get("stt")), tts=make_tts(voice.get("tts")),
                             auto_resume=bool(gw.get("auto_resume", False)),
                             max_sessions=int(gw.get("max_sessions", 500)),
                             reactions=bool(gw.get("reactions", False)),
                             **_endpoint_kwargs_from_cfg(cfg))

    eps: list[AgentEndpoint] = []
    seen_tokens: dict[str, str] = {}                   # token → 1º agente que o usou (anti-conflito multi-profile)
    for aid, spec in agents.items():
        chans = spec.raw.get("channels") or {}
        cfg = None
        tg = chans.get("telegram") or {}
        if tg.get("token") and tg["token"] in seen_tokens:   # 2 agentes, MESMO token → caos (msgs duplicadas)
            emit(f"⚠ [{aid}] usa o MESMO token de Telegram de '{seen_tokens[tg['token']]}' — pulei este "
                 f"agente (um token por agente). Crie outro bot no @BotFather p/ '{aid}'.")
            tg = {}                                     # zera → não sobe este canal
        if tg.get("token"):                            # Telegram (mantém make_channel p/ os testes)
            seen_tokens[tg["token"]] = aid
            cfg = effective_config(global_raw, spec)
            if not tg.get("allow_chats") and not tg.get("allow_all"):   # fail-closed: avisa ALTO
                emit(f"⚠ [{aid}] Telegram SEM allowlist → deny-by-default (bot não responde ninguém). "
                     f"Resolva fácil: `okami setup channel` (detecta teu chat_id sozinho) — ou edite "
                     f"channels.telegram.allow_chats: [<seu_chat_id>] / allow_all: true (inseguro).")
            channel = (make_channel or TelegramChannel)(tg["token"], allow_chats=tg.get("allow_chats"),
                                                        allow_all=bool(tg.get("allow_all", False)))
            eps.append(_mk_endpoint(aid, spec, cfg, channel))
            emit(f"agente '{aid}' no ar (canal {channel.name})")
            _warn_capability_grants(cfg, channel, bool(tg.get("allow_all", False)), aid, emit)
        from okami.gateway.channel_registry import rest_channel_types
        for ctype in rest_channel_types():                   # #15: canais REST do registry (sem if/elif)
            cc = chans.get(ctype) or {}
            if not cc.get("token"):
                continue
            try:
                channel = _build_channel(ctype, cc)
            except KeyError as e:
                emit(f"⚠ [{aid}] {ctype}: faltando campo {e} — pulei esse canal.")
                continue
            if not cc.get("allow_chats") and not cc.get("allow_all"):
                emit(f"⚠ [{aid}] {ctype} sem allowlist → só o canal configurado responde (deny-by-default).")
            cfg = cfg or effective_config(global_raw, spec)
            eps.append(_mk_endpoint(aid, spec, cfg, channel))
            emit(f"agente '{aid}' no ar (canal {channel.name})")
            _warn_capability_grants(cfg, channel, bool(cc.get("allow_all", False)), aid, emit)
    return eps


def _warn_capability_grants(cfg, channel, allow_all: bool, aid: str, emit) -> None:
    """Alerta de boot quando o dono libera shell/processo (tools.shell/process/spawn) numa superfície
    remota — defesa-em-profundidade + consentimento informado (fix do bug ao vivo)."""
    from okami.core.tool_policy import capability_warnings, surface_of
    for w in capability_warnings(surface_of(channel), getattr(cfg, "tools", None) or {}, allow_all=allow_all):
        emit(f"[{aid}] {w}")


def _start_scheduler(eps: list, emit: Callable[[str], None], interval: float = 30.0) -> None:
    """Sobe o scheduler (§11): a cada `interval`s roda jobs vencidos e ENTREGA o resultado no chat."""
    from okami.automation.scheduler import Scheduler

    sched = Scheduler(".")
    if not sched.load():
        return
    by_agent = {ep.agent_id: ep for ep in eps}

    def execute(job):
        ep = by_agent.get(job.get("agent")) or (eps[0] if eps else None)
        if ep is None:
            return "(sem endpoint p/ entregar)"
        from okami.automation.scheduler import delivery_decision, delivery_targets, gate_allows, run_script
        if not gate_allows(job, cwd=str(ep.ws)):       # wake-gate: condição barata falhou → não acorda o LLM
            return "(gate: condição não bateu — agente não foi acordado)"
        if job.get("script"):                          # job SCRIPT (item 30): roda comando, sem gastar LLM
            result = run_script(job["script"], cwd=str(ep.ws))
        else:
            task = ep.run_task(ep.cfg, ep.ws, job["prompt"], agent_home=ep.home, open_fs=ep.open_fs)
            result = task.result or task.reason or task.state.value
        deliver, text = delivery_decision(result)      # [SILENT] → registra mas não manda pro chat
        sched.record_output(job["id"], text)           # item 30: histórico do output (não some após entregar)
        if deliver:                                    # multi-alvo ("123,456") ou a CASA (/sethome)
            for tg in delivery_targets(job.get("target"), home=ep.home_chat()):
                ep.channel.send(tg, f"⏰ {job['id']}: {text}")
        return text

    def loop():
        while True:
            try:
                sched.tick(execute)
            except Exception:  # noqa: BLE001 — scheduler nunca derruba o gateway
                pass
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()
    emit(f"⏰ scheduler no ar ({len(sched.load())} job(s)).")


def _warn_unisolated_exposure(global_raw: dict, endpoints: list, emit: Callable[[str], None]) -> bool:
    """#2: ao EXPOR canal (gateway público) SEM isolamento real, avisa GRITANTE. CLI/dev seguem sem
    atrito — isto só dispara no gateway. Retorna True se avisou (exposto + sem Docker + sem strict)."""
    from okami.core.sandbox import SandboxPolicy
    sb = SandboxPolicy.from_config((global_raw or {}).get("sandbox") or {})
    if bool(sb.require_isolation) or sb.effective_backend() == "docker":
        return False                                  # isolamento real (Docker/strict) → ok, sem aviso
    names = ", ".join(sorted({getattr(ep, "channel", None) and getattr(ep.channel, "name", "") or ""
                              for ep in endpoints} - {""})) or "canais"
    emit("⚠️  ATENÇÃO — SUPERFÍCIE EXPOSTA SEM ISOLAMENTO REAL")
    emit(f"    Você está expondo {names} mas o sandbox não tem isolamento (Docker ausente / "
         "require_isolation desligado).")
    emit("    run_shell/process rodam NO HOST — risco real p/ uso público ('qualquer um manda mensagem').")
    emit("    → Ligue isolamento:  okami harden        (sandbox.require_isolation: true)")
    emit("    → Ou rode com Docker, ou aceite o risco em ambiente CONTROLADO. Ver docs/PRODUCTION.md.")
    return True


def run_gateway(global_raw: dict, agents: dict, emit: Callable[[str], None] = print, make_channel=None):
    from okami.config import build_config

    eps = build_endpoints(global_raw, agents, emit=emit, make_channel=make_channel)   # DMs (1 agente/chat)
    groups = build_group_endpoints(global_raw, agents, build_config(global_raw).groups, emit=emit)  # salas
    everyone = [*eps, *groups]
    if not everyone:
        emit("nada a rodar (nenhum agente com channels.telegram.token, nem grupo).")
        return everyone
    _warn_unisolated_exposure(global_raw, everyone, emit)   # #2: aviso forte se expõe canal SEM isolamento real
    for ep in eps:                                     # boot: limpa sessões velhas + retoma interrompidas
        try:
            n = ep.prune_sessions(max_sessions=ep.max_sessions)
            if n:
                emit(f"agente '{ep.agent_id}': {n} sessão(ões) antiga(s) podada(s)")
            ep.resume_interrupted(auto_resume=ep.auto_resume)
        except Exception:  # noqa: BLE001
            pass
    for ep in everyone:
        threading.Thread(target=ep.loop, daemon=True).start()
    _start_scheduler(eps, emit)                        # §11: jobs agendados entregam no chat
    try:                                               # watchdog de memória (grep [MEMORY] → vazamento lento)
        from okami.observability.memwatch import start_memory_watch
        start_memory_watch(emit)
    except Exception:  # noqa: BLE001 — observabilidade nunca derruba o boot
        pass
    emit(f"gateway no ar: {len(eps)} agente(s) DM + {len(groups)} grupo(s). Ctrl+C para sair.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for ep in everyone:
            ep.running = False
    return everyone
