"""Builders do gateway: monta AgentEndpoint/GroupEndpoint a partir da config, scheduler e run_gateway."""

from __future__ import annotations

import threading
import time
from typing import Callable

from okami.gateway.endpoint import AgentEndpoint
from okami.gateway.group import GroupEndpoint


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
    """Fábrica de canal não-Telegram (#15). KeyError se faltar um campo obrigatório."""
    common = {"allow_chats": cc.get("allow_chats"), "allow_all": bool(cc.get("allow_all", False))}
    if ctype == "slack":
        from okami.channels.slack import SlackChannel
        return SlackChannel(cc["token"], cc["channel_id"], **common)
    if ctype == "discord":
        from okami.channels.discord import DiscordChannel
        return DiscordChannel(cc["token"], cc["channel_id"], **common)
    if ctype == "mattermost":
        from okami.channels.mattermost import MattermostChannel
        return MattermostChannel(cc["base_url"], cc["token"], cc["channel_id"], **common)
    raise KeyError(ctype)


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
                             reactions=bool(gw.get("reactions", False)))

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
        for ctype in ("slack", "discord", "mattermost"):     # #15: mais canais, mesma interface
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
    return eps


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
        task = ep.run_task(ep.cfg, ep.ws, job["prompt"])
        result = task.result or task.reason or task.state.value
        target = job.get("target") or ep.home_chat()   # alvo explícito, senão a CASA (/sethome)
        if target:                                     # entrega no chat (estilo OpenClaw cron→canal)
            ep.channel.send(target, f"⏰ {job['id']}: {result}")
        return result

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
    emit(f"gateway no ar: {len(eps)} agente(s) DM + {len(groups)} grupo(s). Ctrl+C para sair.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for ep in everyone:
            ep.running = False
    return everyone
