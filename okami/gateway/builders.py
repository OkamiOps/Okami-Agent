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


def _parse_email_cc(cc: dict) -> dict:
    """#19: normaliza channels.email (resolve app-password via env/secret_sources, default Gmail de
    host/port) ANTES do build_channel — o EmailChannel é keyword-only (user/app_password, sem token).
    Fail-graceful: se o parser ainda não existir em runtime (spec a meio de chegar), devolve a config
    crua — o build_channel/required_keys cuida do que faltar."""
    try:
        from okami.config import parse_email_channel
    except ImportError:
        return cc or {}
    return parse_email_channel(cc or {})


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
            if ctype == "email":                             # #19: e-mail é keyword-only (user/app_password,
                cc = _parse_email_cc(cc)                     # sem token) → parseia (resolve segredo/host) antes
                if not cc.get("user") or not cc.get("app_password"):
                    continue                                 # sem credencial → pula (não há token p/ gatear)
            elif not cc.get("token"):
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


def _make_desktop_notifier(global_raw: dict) -> Callable[[str, str], None]:
    """#4: devolve um notificador de DESKTOP (toast) honrando `notifications.desktop`. Se a flag não
    está ligada, devolve um no-op (zero custo). É best-effort: qualquer falha do sink é engolida — uma
    notificação nunca derruba a entrega (mesma doutrina do okami.core.desktop)."""
    on = bool(((global_raw or {}).get("notifications") or {}).get("desktop", False))
    if not on:
        return lambda title, body: None                # desligado → no-op silencioso

    def _notify(title: str, body: str) -> None:
        try:
            from okami.core.desktop import desktop_notify
            desktop_notify(title, body)
        except Exception:  # noqa: BLE001 — best-effort: sink quebrou/sumiu, segue a vida
            pass

    return _notify


def _start_scheduler(eps: list, emit: Callable[[str], None], interval: float = 30.0,
                     desktop_notify=None) -> None:
    """Sobe o scheduler (§11): a cada `interval`s roda jobs vencidos e ENTREGA o resultado no chat.
    Quando `desktop_notify` está ligado (#4), também solta um toast de desktop na entrega."""
    from okami.automation.scheduler import Scheduler

    sched = Scheduler(".")
    if not sched.load():
        return
    by_agent = {ep.agent_id: ep for ep in eps}
    toast = desktop_notify or (lambda title, body: None)

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
            toast(f"⏰ {ep.agent_id}", f"{job['id']}: {text}")   # #4: toast desktop (best-effort)
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


def _commitment_tick_once(eps: list, now_ts: float | None = None,
                          emit: Callable[[str], None] = lambda m: None) -> None:
    """#10: UMA volta do tick de compromissos INFERIDOS. Para cada endpoint: expira os velhos, pega os
    vencidos do CommitmentStore (raiz = home do agente) e ENTREGA na casa via `safe_delivery_text`
    (NUNCA texto cru do turno — guard de injeção persistida), marcando cada um como 'sent'.

    Fail-open: qualquer erro num endpoint é engolido — esta camada de fundo nunca derruba o gateway.
    A EXTRAÇÃO em si (que popula o store) é gatilhada no endpoint por outro caminho; aqui só o TICK
    de entrega."""
    from okami.automation.commitments import CommitmentStore, safe_delivery_text

    now = now_ts if now_ts is not None else time.time()
    for ep in eps:
        try:
            store = CommitmentStore(getattr(ep, "home", None) or getattr(ep, "ws", "."))
            store.expire(now)                          # ciclo: pending velho demais → expired (não entrega)
            home = ep.home_chat()
            if not home:
                continue                               # sem casa (/sethome) → não há p/ onde entregar
            from okami.core.redact import redact
            for c in store.due(now):
                # redact: o summary vem de um modelo aux que LEU os turnos (onde pode haver segredo
                # colado) — entrega ao chat NUNCA vai crua (safe_delivery_text só barra replay, não segredo).
                ep.channel.send(home, "💭 " + redact(safe_delivery_text(c)))
                store.mark(c["id"], "sent")            # marca como entregue → não reentrega
        except Exception:  # noqa: BLE001 — fundo: um endpoint torto não derruba o tick
            continue


def _start_commitment_tick(eps: list, emit: Callable[[str], None], interval: float = 300.0) -> None:
    """#10: sobe a thread do tick de compromissos (irmão do _start_scheduler). A cada `interval`s
    entrega os compromissos vencidos. Sem endpoints → não sobe nada."""
    if not eps:
        return

    def loop():
        while True:
            try:
                _commitment_tick_once(eps, emit=emit)
            except Exception:  # noqa: BLE001 — nunca derruba o gateway
                pass
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()
    emit("💭 tick de compromissos no ar.")


def _start_webhook(global_raw: dict, eps: list, emit: Callable[[str], None],
                   serve: bool = False, desktop_notify=None):
    """#14: monta (e opcionalmente sobe) um WebhookServer a partir de `gateway.webhook`. Leitura
    DEFENSIVA da config: sem bloco ou sem rotas → devolve None (nada exposto, fail-graceful).

    Rotas `deliver_only` → entregam o payload (redigido) DIRETO no chat-casa via channel.send, SEM
    rodar o agente (zero LLM). Rotas de evento → `server.handle(prompt, route)` acorda ep.handle(home,
    prompt sintetizado). `serve=True` abre o socket na própria thread (junto ao scheduler); o default
    `serve=False` só guarda a config (testes / inspeção). A superfície é alimentada no aviso unisolated
    pelo run_gateway. `desktop_notify` (#4): toast best-effort também nas notificações deliver_only."""
    from okami.channels.webhook import WebhookRoute, WebhookServer

    gw = (global_raw or {}).get("gateway") or {}
    wcfg = gw.get("webhook") or {}
    raw_routes = wcfg.get("routes") or {}
    if not raw_routes:
        return None                                    # sem rotas → nada a expor

    ep0 = eps[0] if eps else None                      # casa/destino: 1º endpoint (DM principal)
    toast = desktop_notify or (lambda title, body: None)
    # postura fail-SAFE (igual config.parse_webhook): default no nível do webhook é DELIVER_ONLY True —
    # uma porta exposta só ENTREGA (não acorda o agente) até o dono pôr deliver_only: false na rota.
    default_deliver_only = bool(wcfg.get("deliver_only", True))

    def _make_deliver(ep):
        def _deliver(body: bytes, route: "WebhookRoute") -> None:
            """deliver_only: repassa o payload (REDIGIDO) ao chat-casa SEM acordar o agente."""
            if ep is None:
                return
            from okami.core.redact import redact
            target = route.chat_id or ep.home_chat()
            if not target:
                return
            text = redact(body.decode("utf-8", "replace"))[:2000]
            ep.channel.send(target, f"🔔 {route.provider}: {text}")
            toast(f"🔔 {route.provider}", text)        # #4: toast desktop best-effort
        return _deliver

    routes: dict[str, WebhookRoute] = {}
    for path, rc in raw_routes.items():
        rc = rc or {}
        deliver_only = bool(rc.get("deliver_only", default_deliver_only))   # rota herda o default do webhook
        routes[path] = WebhookRoute(
            provider=str(rc.get("provider", "generic")),
            secret=str(rc.get("secret", "")),
            chat_id=str(rc.get("chat_id", "")),
            deliver_only=deliver_only,
            deliver=_make_deliver(ep0) if deliver_only else None,
            header=str(rc.get("header", "X-Signature")),
            tolerance=int(rc.get("tolerance", 300)),
            prompt_prefix=str(rc.get("prompt_prefix", "")),
        )

    def _handle(prompt: str, route: "WebhookRoute") -> None:
        """rota de evento: acorda o agente com o prompt sintetizado, na casa (ou chat_id da rota).

        #13: roteia sob surface='webhook' (per-chamada, sem mutar ep0.surface → thread-safe vs. o poll
        concorrente do canal-base). O evento é só HMAC-autenticado → NÃO deve herdar a surface do
        canal-base (telegram/email) nem os capability grants de shell do dono; cai na _DENY_BY_SURFACE
        ['webhook'] (run_shell/execute_code negados por padrão)."""
        if ep0 is None:
            return
        target = route.chat_id or ep0.home_chat()
        if not target:
            return
        ep0.handle(target, prompt, surface_override="webhook")

    srv = WebhookServer(host=str(wcfg.get("host", "127.0.0.1")), port=int(wcfg.get("port", 8788)),
                        routes=routes, handle=_handle, serve=serve)
    if serve:                                          # socket real → loop na própria thread (não bloqueia)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    emit(f"🪝 webhook no ar ({len(routes)} rota(s)) em {srv.host}:{srv.port}.")
    return srv


def _warn_unisolated_exposure(global_raw: dict, endpoints: list, emit: Callable[[str], None],
                              extra_surfaces: list | None = None) -> bool:
    """#2: ao EXPOR canal (gateway público) SEM isolamento real, avisa GRITANTE. CLI/dev seguem sem
    atrito — isto só dispara no gateway. `extra_surfaces` (#14): superfícies não-canal já expostas
    (ex.: WebhookServer) entram na lista de nomes avisados. Retorna True se avisou (exposto + sem
    Docker + sem strict)."""
    from okami.core.sandbox import SandboxPolicy
    sb = SandboxPolicy.from_config((global_raw or {}).get("sandbox") or {})
    if bool(sb.require_isolation) or sb.effective_backend() == "docker":
        return False                                  # isolamento real (Docker/strict) → ok, sem aviso
    surface_names = {getattr(ep, "channel", None) and getattr(ep.channel, "name", "") or ""
                     for ep in endpoints}
    for s in (extra_surfaces or []):                   # #14: webhook (sem .channel, mas é superfície exposta)
        if s is not None:
            surface_names.add("webhook")
    names = ", ".join(sorted(surface_names - {""})) or "canais"
    emit("⚠️  ATENÇÃO — SUPERFÍCIE EXPOSTA SEM ISOLAMENTO REAL")
    emit(f"    Você está expondo {names} mas o sandbox não tem isolamento (Docker ausente / "
         "require_isolation desligado).")
    emit("    run_shell/process rodam NO HOST — risco real p/ uso público ('qualquer um manda mensagem').")
    emit("    → Ligue isolamento:  okami harden        (sandbox.require_isolation: true)")
    emit("    → Ou rode com Docker, ou aceite o risco em ambiente CONTROLADO. Ver docs/PRODUCTION.md.")
    return True


def run_gateway(global_raw: dict, agents: dict, emit: Callable[[str], None] = print, make_channel=None):
    from okami.config import build_config

    # #11: preflight de CA bundle SSL — pega env var de CA quebrada ANTES do 1º HTTPS (erro acionável,
    # não FileNotFoundError opaco lá na frente). Best-effort: não derruba o boot.
    try:
        from okami.llm.ssl_guard import verify_ca_bundle
        verify_ca_bundle()
    except Exception as e:  # noqa: BLE001
        emit(f"⚠ SSL/CA bundle: {e}")
    # #11: panic-hook — crash não-tratado do gateway vira traceback em ~/.okami/logs/gateway_crash.log
    # + 1-linha no stderr (senão some: stdout/feed não captura). Best-effort.
    try:
        from okami.gateway.panic_hook import install_panic_hook
        from okami.home import okami_home
        install_panic_hook(okami_home() / "logs" / "gateway_crash.log")
    except Exception:  # noqa: BLE001
        pass

    eps = build_endpoints(global_raw, agents, emit=emit, make_channel=make_channel)   # DMs (1 agente/chat)
    groups = build_group_endpoints(global_raw, agents, build_config(global_raw).groups, emit=emit)  # salas
    everyone = [*eps, *groups]
    if not everyone:
        emit("nada a rodar (nenhum agente com channels.telegram.token, nem grupo).")
        return everyone
    toast = _make_desktop_notifier(global_raw)         # #4: toast desktop (no-op se notifications.desktop off)
    try:                                               # porta ocupada/bind falho NÃO derruba o gateway
        webhook = _start_webhook(global_raw, eps, emit, serve=True, desktop_notify=toast)  # #14
    except Exception as e:  # noqa: BLE001 — mesma doutrina dos outros _start_* (best-effort)
        emit(f"⚠ webhook não subiu ({e}) — gateway segue sem webhook.")
        webhook = None
    _warn_unisolated_exposure(global_raw, everyone, emit,   # #2: aviso forte se expõe SEM isolamento real
                              extra_surfaces=[webhook] if webhook else None)
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
    _start_scheduler(eps, emit, desktop_notify=toast)  # §11: jobs agendados entregam no chat (+ toast #4)
    _start_commitment_tick(eps, emit)                  # #10: compromissos inferidos entregam na casa
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
