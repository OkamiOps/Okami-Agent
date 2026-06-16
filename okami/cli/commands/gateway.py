"""Gateway/daemon: gateway · serve · room · heartbeat · route · mcp."""
from __future__ import annotations

import sys

import typer
from okami.i18n import t as _tr
from rich.table import Table
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load,
)


@app.command("pair", help=_tr("cli.pair", _default="Approve chats dynamically: okami pair list|approve <code>|add <chat_id>|revoke <chat_id>."))
def pair(
    action: str = typer.Argument(..., help=_tr("cli.pair.action", _default="list | approve | add | revoke.")),
    value: str = typer.Argument("", help=_tr("cli.pair.value", _default="code (approve) or chat_id (add/revoke).")),
    agent: str = typer.Option(None, "--agent", "-a", help=_tr("cli.pair.agent", _default="Agent whose allowlist to manage (default: current workspace).")),
    workspace: str = typer.Option(".", "--workspace", "-w", help=_tr("cli.pair.ws", _default="Workspace/home dir (default: current).")),
) -> None:
    """Pareamento dinâmico (dono): aprova chats que pediram acesso, sem editar agent.yaml na mão."""
    from okami.cli._shared import _persona_ws
    from okami.gateway.pairing import PairingStore
    store = PairingStore(_persona_ws(agent, workspace))
    act = action.strip().lower()
    if act == "list":
        pend = store.pending()
        appr = store.approved()
        if pend:
            t = Table(title="pareamentos pendentes")
            t.add_column("código", style="bold")
            t.add_column("chat_id")
            for p in pend:
                t.add_row(p["code"], str(p["chat_id"]))
            console.print(t)
        else:
            console.print("[dim]nenhum pedido de pareamento pendente.[/dim]")
        console.print(f"[dim]aprovados:[/dim] {', '.join(appr) if appr else '—'}")
        return
    if act == "approve":
        cid = store.approve(value)
        if cid:
            console.print(f"[green]✓ chat {cid} aprovado[/green] (código {value.strip().upper()}).")
        else:
            console.print(f"[red]código '{value}' inválido ou expirado.[/red]")
            raise typer.Exit(1)
        return
    if act == "add":
        if not value.strip():
            console.print("[red]informe o chat_id:[/red] okami pair add <chat_id>")
            raise typer.Exit(2)
        store.approve_chat(value.strip())
        console.print(f"[green]✓ chat {value.strip()} aprovado[/green] (direto).")
        return
    if act == "revoke":
        if store.revoke(value.strip()):
            console.print(f"[green]✓ chat {value.strip()} revogado.[/green]")
        else:
            console.print(f"[yellow]chat {value.strip()} não estava aprovado.[/yellow]")
        return
    console.print(f"[red]ação '{action}' não reconhecida[/red] — use: list | approve | add | revoke")
    raise typer.Exit(2)


def _gateway_files() -> tuple[Path, Path]:
    """Estado do gateway na CASA (~/.okami), não espalhado no CWD: runtime/gateway.pid + logs/gateway.log.
    Lê do legado .okami/ do CWD só pra migração (não cria mais lá)."""
    from okami.home import okami_home
    home = okami_home()
    (home / "runtime").mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(parents=True, exist_ok=True)
    pid, log = home / "runtime" / "gateway.pid", home / "logs" / "gateway.log"
    legacy = Path(".okami") / "gateway.pid"
    if not pid.exists() and legacy.exists():          # gateway antigo subiu no CWD → reaproveita o pid p/ stop/status
        pid = legacy
    return pid, log


def _pid_alive(pid: int) -> bool:
    import os
    if os.name == "nt":
        import subprocess
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _gw_state():
    """(pidfile, logfile, pid|None, alive) — estado atual do gateway em background."""
    pidfile, logfile = _gateway_files()
    pid = int(pidfile.read_text()) if pidfile.exists() and pidfile.read_text().strip().isdigit() else None
    return pidfile, logfile, pid, (pid is not None and _pid_alive(pid))


def _gw_stop(quiet_if_stopped: bool = False) -> bool:
    """Para o gateway (SIGTERM + espera morrer). True se havia um rodando."""
    import os
    import subprocess
    import time
    pidfile, _, pid, alive = _gw_state()
    if not alive:
        if not quiet_if_stopped:
            console.print("[dim]gateway não está rodando.[/dim]")
        pidfile.unlink(missing_ok=True)
        return False
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        import signal
        os.kill(pid, signal.SIGTERM)
    for _ in range(50):                              # espera ATÉ morrer (restart não pode correr c/ o velho)
        if not _pid_alive(pid):
            break
        time.sleep(0.1)
    pidfile.unlink(missing_ok=True)
    console.print(f"[yellow]⏹ gateway parado[/yellow] (pid {pid})")
    return True


def _gw_start_background() -> None:
    """Sobe o gateway destacado (background) e devolve o terminal."""
    import os
    import subprocess
    pidfile, logfile, pid, alive = _gw_state()
    from okami.agents import load_agents
    if not load_agents():
        console.print("[yellow]nenhum agente. Crie com: okami agent new <id>[/yellow]")
        raise typer.Exit(1)
    if alive:
        console.print(f"[yellow]gateway já está no ar[/yellow] (pid {pid}). "
                      "Reinicie com: okami gateway restart")
        return
    flags = {}
    if os.name == "nt":
        flags["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        flags["start_new_session"] = True
    log = open(logfile, "a", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "okami.cli", "gateway", "--foreground"],
                            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            cwd=os.getcwd(), **flags)
    pidfile.write_text(str(proc.pid))
    console.print(f"[green]🤖 gateway no ar em background[/green] (pid {proc.pid}) — terminal livre.")
    console.print("[dim]logs:[/dim] okami logs -f   [dim]status:[/dim] okami gateway status   "
                  "[dim]reiniciar:[/dim] okami gateway restart   [dim]parar:[/dim] okami gateway stop")


_GW_ACTIONS = ("start", "stop", "status", "restart")


@app.command(help=_tr("cli.gateway", _default="Telegram bots (1 per agent): okami gateway [start|stop|status|restart]. Background by default."))
def gateway(
    action: str = typer.Argument("start", help=_tr("cli.gateway.action", _default="start (default) | stop | status | restart")),
    foreground: bool = typer.Option(False, "-f", "--foreground",
                                    help=_tr("cli.gateway.foreground", _default="Run in the terminal (live logs, Ctrl+C to exit).")),
    stop: bool = typer.Option(False, "--stop", help=_tr("cli.gateway.stop", _default="(alias) = okami gateway stop")),
    status: bool = typer.Option(False, "--status", help=_tr("cli.gateway.status", _default="(alias) = okami gateway status")),
) -> None:
    """Ciclo de vida do gateway: start (default, background) · stop · status · restart.
    As flags --stop/--status seguem valendo (alias). -f roda em primeiro plano (Ctrl+C sai)."""
    act = "stop" if stop else "status" if status else action.strip().lower()
    if act not in _GW_ACTIONS:
        console.print(f"[red]ação '{action}' não reconhecida.[/red] Use: [bold]start[/bold] (default) · "
                      "[bold]stop[/bold] · [bold]status[/bold] · [bold]restart[/bold]")
        raise typer.Exit(2)

    if act == "status":
        _, logfile, pid, alive = _gw_state()
        console.print(f"[green]● no ar[/green] (pid {pid}) · log: {logfile}" if alive
                      else "[dim]○ parado[/dim]")
        return
    if act == "stop":
        _gw_stop()
        return
    if act == "restart":
        _gw_stop(quiet_if_stopped=True)              # parado → só sobe (restart idempotente)
        _gw_start_background()
        return

    # start
    if foreground:                                   # primeiro plano: logs ao vivo, bloqueia (Ctrl+C)
        from okami.agents import load_agents
        if not load_agents():
            console.print("[yellow]nenhum agente. Crie com: okami agent new <id>[/yellow]")
            raise typer.Exit(1)
        from okami.config import load_raw
        from okami.gateway import run_gateway
        graw, _ = load_raw()
        run_gateway(graw, load_agents(), emit=lambda m: console.print(f"🤖 {m}"))
        return
    _gw_start_background()


@app.command(help=_tr("cli.serve", _default="Start the HTTP API (POST /chat with a Bearer token). Requires OKAMI_API_TOKEN in .env (fail-closed)."))
def serve(
    port: int = typer.Option(8765, "-p", "--port"),
    host: str = typer.Option("127.0.0.1", "--host", help=_tr("cli.serve.host", _default="127.0.0.1 (local) by default; 0.0.0.0 exposes to the network.")),
    ws: bool = typer.Option(False, "--ws", help=_tr("cli.serve.ws", _default="WebSocket attach mode (talk from `okami attach`, multi-turn) instead of one-shot POST /chat.")),
) -> None:
    """Sobe a API HTTP (POST /chat) ou, com --ws, o attach por WebSocket. Requer OKAMI_API_TOKEN (fail-closed)."""
    import os
    from okami.agents import effective_config, load_agents
    from okami.api import serve as _serve
    from okami.config import load_raw
    from okami.runner import run_task as _rt

    cfg = _load()
    token = os.getenv("OKAMI_API_TOKEN")
    if not token:
        console.print("[red]✗ defina OKAMI_API_TOKEN:[/red] okami config set OKAMI_API_TOKEN <um-token-secreto>")
        raise typer.Exit(1)

    def run(agent_id: str, message: str):
        graw, _ = load_raw()
        spec = load_agents().get(agent_id)
        c, ws_dir = (effective_config(graw, spec), spec.dir) if spec else (cfg, Path("workspaces/default"))
        ws_dir.mkdir(parents=True, exist_ok=True)
        return _rt(c, ws_dir, message)

    if ws:                                          # ATTACH por WebSocket (multi-turno, casa com tailscale)
        from collections import defaultdict
        from okami.gateway.wsattach import serve_ws
        hist: dict = defaultdict(list)              # session -> [(papel, texto)] p/ continuidade da conversa
        wdir = Path("workspaces/default")
        wdir.mkdir(parents=True, exist_ok=True)

        def run_ws(message: str, session: str = "") -> str:
            prior = hist[session][-12:]
            ctx = "Conversa até aqui:\n" + "\n".join(f"{r}: {t}" for r, t in prior) if prior else ""
            t = _rt(cfg, wdir, message, extra_context=ctx)
            reply = t.result or t.reason or t.state.value
            hist[session].extend([("você", message), ("okami", reply)])
            return reply

        srv = _serve_ws_or_http(serve_ws, port, token, run_ws, host, attach_dir=str(wdir))
        console.print(f"[green]🛰  attach por WS no ar[/green] ws://{host}:{port}/attach  "
                      f"[dim](conecte com: okami attach ws://{host}:{port}/attach)[/dim]")
        if host == "127.0.0.1":
            console.print("[dim]p/ alcançar de outra máquina (tailscale): --host <ip-da-tailnet> ou 0.0.0.0[/dim]")
    else:
        srv = _serve(port, token, run, host=host)
        console.print(f"[green]🌐 API no ar[/green] http://{host}:{port}  "
                      f"[dim](POST /chat · Authorization: Bearer …)[/dim]")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
        console.print("[dim]servidor parado.[/dim]")


def _serve_ws_or_http(serve_ws, port, token, run_ws, host, *, attach_dir=None):
    return serve_ws(port, token, run_ws, host=host, attach_dir=attach_dir)


@app.command(help=_tr("cli.dump", _default="One-screen, paste-able status for a bug report (secrets redacted)."))
def dump() -> None:
    """Imprime uma tela humano-colável (home/commit/providers/canais/skills) — segredo redigido."""
    from okami.core.dump import build_dump
    try:
        cfg = _load()
    except Exception:  # noqa: BLE001 — dump tem que funcionar mesmo com config quebrada
        cfg = None
    console.print(build_dump(cfg), markup=False, highlight=False)   # verbatim (colável, sem comer [..])


@app.command(help=_tr("cli.backup", _default="Snapshot the whole ~/.okami HOME (config/memory/skills/cron) to a zip (consistent SQLite)."))
def backup(dest: str = typer.Option(".", "--dest", "-d", help=_tr("cli.backup.dest", _default="Directory for the backup zip."))) -> None:
    """Snapshot zipado do HOME inteiro (config/memória/skills/cron) — portátil entre máquinas."""
    from okami.core.backup import create_backup
    from okami.home import okami_home
    p = create_backup(okami_home(), dest)
    console.print(f"[green]✓ backup[/green] {p}  [dim]({p.stat().st_size // 1024} KB)[/dim]")
    console.print(f"[dim]restaure noutra máquina com: okami import {p.name}[/dim]")


@app.command("import", help=_tr("cli.import", _default="Restore a ~/.okami backup zip (anti zip-slip; re-chmods secrets to 0600)."))
def import_backup(
    zip_path: str = typer.Argument(..., help=_tr("cli.import.zip", _default="Path to the okami-backup-*.zip")),
    home: str = typer.Option(None, "--home", help=_tr("cli.import.home", _default="Target HOME (default: ~/.okami)")),
) -> None:
    """Restaura um backup do HOME (guarda anti zip-slip + re-chmod 0600 nos segredos)."""
    from okami.core.backup import restore_backup
    from okami.home import okami_home
    n = restore_backup(zip_path, home or okami_home())
    console.print(f"[green]✓ restaurados[/green] {n} arquivo(s) em {home or okami_home()}")


@app.command(help=_tr("cli.attach", _default="Attach to a remote okami gateway over WebSocket (start it with `okami serve --ws`)."))
def attach(
    url: str = typer.Argument(..., help=_tr("cli.attach.url", _default="ws://<host>:<port>/attach (e.g. a tailscale host)")),
    token: str = typer.Option(None, "--token", help=_tr("cli.attach.token", _default="token (default: $OKAMI_API_TOKEN)")),
) -> None:
    """Conecta a um gateway remoto por WebSocket e conversa (multi-turno). Casa com ssh/tailscale."""
    import os

    from okami.gateway.wsattach import WSClient
    tok = token or os.getenv("OKAMI_API_TOKEN") or ""
    client = WSClient()
    try:
        client.connect(url, token=tok)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]✗ não conectei a {url}:[/red] {e}")
        raise typer.Exit(1)
    console.print(f"[green]🛰  conectado[/green] {url}  [dim](Ctrl-D ou /exit p/ sair)[/dim]")
    try:
        from rich.markdown import Markdown
        while True:
            try:
                line = console.input("[bold #ff7527]›[/bold #ff7527] ")
            except (EOFError, KeyboardInterrupt):
                break
            if not line.strip():
                continue
            if line.strip().lower() in ("/exit", "/quit", "exit", "quit"):
                break
            if line.strip().startswith("/attach "):       # #10: manda um arquivo local pro gateway remoto
                fp = Path(line.strip()[len("/attach "):].strip().strip('"\''))
                if not fp.is_file():
                    console.print(f"[red]arquivo não encontrado: {fp}[/red]")
                    continue
                client.send_attach(fp.name, fp.read_bytes())
                console.print(Markdown(client.recv() or "(sem resposta)"))
                continue
            client.send(line)
            reply = client.recv()
            if reply is None:
                console.print("[dim]conexão encerrada pelo servidor.[/dim]")
                break
            console.print(Markdown(reply))
    finally:
        client.close()
        console.print("[dim]desconectado.[/dim]")


@app.command(help=_tr("cli.room", _default="Multi-agent brainstorm: the moderator decides who speaks (or nobody), no stampede."))
def room(
    message: str = typer.Argument(..., help=_tr("cli.room.message", _default="User message to the group (use @id to mention).")),
    group: int = typer.Option(0, "--group", "-g", help=_tr("cli.room.group", _default="Group index in okami.yaml (groups).")),
    provider: str = typer.Option(None, "--moderator", help=_tr("cli.room.moderator", _default="Cheap provider for the moderator.")),
) -> None:
    """Brainstorm multi-agente: o moderador decide quem fala (ou ninguém), sem stampede."""
    from okami.agents import effective_config, load_agents
    from okami.config import load_raw
    from okami.agents.group import agent_responder, build_room, llm_moderator, parse_mentions

    graw, _ = load_raw()
    cfg = _load()
    if not cfg.groups or group >= len(cfg.groups):
        console.print("[yellow]nenhum grupo em okami.yaml (groups). Ex.: groups: [{members: [cto, ui]}][/yellow]")
        raise typer.Exit(1)
    agents = load_agents()
    gcfg = cfg.groups[group]
    room_obj = build_room(graw, agents, gcfg,
                          select_speaker=llm_moderator(cfg, provider=provider),
                          respond=agent_responder(graw, agents))

    def _model_of(aid: str) -> str:                  # modelo PRÓPRIO do agente (verifica isolamento)
        try:
            eff = effective_config(graw, agents[aid])
            return f"{eff.default_provider}:{eff.provider().model}"
        except Exception:  # noqa: BLE001
            return "?"

    roster = ", ".join(f"{m.id} ({_model_of(m.id)})" for m in room_obj.members)   # () não [] (Rich markup)
    console.print(f"[dim]grupo: {roster}[/dim]")
    mentioned = parse_mentions(message, {m.id for m in room_obj.members})
    console.print(f"[bold]você:[/bold] {message}")
    replies = room_obj.dispatch("USER", message, mentioned=mentioned)
    if not replies:
        console.print("[dim](ninguém se manifestou — sem stampede)[/dim]")
    for agent_id, text in replies:
        console.print(f"[bold cyan]{agent_id}[/bold cyan] [dim]({_model_of(agent_id)})[/dim]: {text}")


@app.command(help=_tr("cli.heartbeat", _default="One Paperclip heartbeat: picks up the assigned issue, works on it, and reports (§11)."))
def heartbeat(
    agent: str = typer.Option(None, "-a", "--agent", help=_tr("cli.heartbeat.agent", _default="Okami agent (own workspace/config) to run.")),
    workspace: str = typer.Option(".", "-w", "--workspace", help=_tr("cli.heartbeat.workspace", _default="Workspace (if not using -a).")),
    mode: str = typer.Option("defer", "--mode", help=_tr("cli.heartbeat.mode", _default="Governance of sensitive actions: defer | yolo | off.")),
) -> None:
    """Uma batida de heartbeat do Paperclip: pega a issue atribuída, trabalha e reporta (§11)."""
    from okami.channels.paperclip import PaperclipError, run_heartbeat
    from okami.runner import run_task

    if agent:
        from okami.agents import effective_config, load_agents
        from okami.config import load_raw
        spec = load_agents().get(agent)
        if not spec:
            console.print(f"[red]agente '{agent}' não encontrado[/red] (okami agent list)")
            raise typer.Exit(1)
        graw, _ = load_raw()
        cfg, ws = effective_config(graw, spec), spec.dir
    else:
        cfg, ws = _load(), Path(workspace)
    try:
        res = run_heartbeat(cfg, ws, run_task=run_task, approve_mode=mode,
                            emit=lambda m: console.print(f"📎 {m}"))
    except PaperclipError as e:
        console.print(f"[red]Paperclip:[/red] {e}")
        raise typer.Exit(1)
    color = {"done": "green", "in_review": "yellow", "blocked": "red", "none": "dim"}.get(res.status, "white")
    console.print(f"[{color}]✓ heartbeat:[/{color}] issue={res.issue_id} status={res.status}")


@app.command(help=_tr("cli.route", _default="Show which agent a source is routed to (bindings §10)."))
def route(source: str = typer.Argument(..., help=_tr("cli.route.source", _default="Source (e.g. telegram:12345) to route."))) -> None:
    """Mostra para qual agente uma origem é roteada (bindings §10)."""
    from okami.agents import build_router, load_agents

    cfg = _load()
    target = build_router(cfg.agents, load_agents()).route(source)
    console.print(f"{source} → [bold]{target or '(sem agente; defina agents.default)'}[/bold]")


service_app = typer.Typer(invoke_without_command=True,
                          help=_tr("cli.service", _default="Gateway as a SERVICE (starts on boot, restarts on crash): launchd/systemd."))
app.add_typer(service_app, name="service")


@service_app.callback(invoke_without_command=True)
def _service_main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from okami.gateway import service
        service.control("status", emit=console.print)


@service_app.command("install", help=_tr("cli.service.install", _default="Install the gateway as an OS service (runs `okami gateway --foreground` on boot, restarts on crash)."))
def service_install() -> None:
    """Instala o gateway como serviço do SO (roda `okami gateway --foreground` no boot, reinicia se cair)."""
    from okami.gateway import service
    if service.install(emit=console.print):
        console.print("[dim]controle: okami service start|stop|restart|status · logs: okami logs -f[/dim]")


@service_app.command("uninstall", help=_tr("cli.service.uninstall", _default="Remove the OS service."))
def service_uninstall() -> None:
    """Remove o serviço do SO."""
    from okami.gateway import service
    service.uninstall(emit=console.print)


@service_app.command("start", help=_tr("cli.service.start", _default="Start the service."))
def service_start() -> None:
    """Inicia o serviço."""
    from okami.gateway import service
    service.control("start", emit=console.print)


@service_app.command("stop", help=_tr("cli.service.stop", _default="Stop the service."))
def service_stop() -> None:
    """Para o serviço."""
    from okami.gateway import service
    service.control("stop", emit=console.print)


@service_app.command("restart", help=_tr("cli.service.restart", _default="Restart the service."))
def service_restart() -> None:
    """Reinicia o serviço."""
    from okami.gateway import service
    service.control("restart", emit=console.print)


@service_app.command("status", help=_tr("cli.service.status", _default="Show whether the service is up."))
def service_status() -> None:
    """Mostra se o serviço está no ar."""
    from okami.gateway import service
    service.control("status", emit=console.print)


@app.command(help=_tr("cli.logs", _default="Show the gateway log (service at ~/.okami/logs/gateway.log, or background at .okami/gateway.log)."))
def logs(
    follow: bool = typer.Option(False, "-f", "--follow", help=_tr("cli.logs.follow", _default="Follow the log live (tail -f).")),
    lines: int = typer.Option(200, "-n", "--lines", help=_tr("cli.logs.lines", _default="How many trailing lines to show.")),
    level: str = typer.Option("", "--level", help=_tr("cli.logs.level", _default="Filter by level (DEBUG/INFO/WARNING/ERROR).")),
    component: str = typer.Option("", "--component", help=_tr("cli.logs.component", _default="Filter by component (gateway/agent/tools/cron).")),
    since: str = typer.Option("", "--since", help=_tr("cli.logs.since", _default="Only lines newer than this window (e.g. 1h, 30m, 2d).")),
) -> None:
    """Mostra o log do gateway (serviço em ~/.okami/logs/gateway.log, ou o background em .okami/gateway.log)."""
    import time as _t

    from okami.gateway import service
    candidates = [service.log_path(), Path(".okami") / "gateway.log"]
    log = next((p for p in candidates if p.exists()), None)
    if log is None:
        console.print("[dim]sem log ainda (suba o gateway: okami gateway · ou okami service install)[/dim]")
        return
    console.print(f"[dim]{log}[/dim]")
    with log.open("r", encoding="utf-8", errors="ignore") as f:
        tail = f.readlines()[-max(1, lines):]
        if level or component or since:                   # #11: filtro multi-eixo
            import time as _now
            from okami.cli.log_filter import filter_log_lines
            tail = filter_log_lines(tail, level=level, component=component, since=since, now=_now.time())
        console.print("".join(tail), end="")
        if not follow:
            return
        try:
            while True:                                   # tail -f simples
                line = f.readline()
                if line:
                    console.print(line, end="")
                else:
                    _t.sleep(0.4)
        except KeyboardInterrupt:
            return


# ─────────────────────────────── supervisão de PROCESSOS (fora do gateway/agente) ───────────────────
process_app = typer.Typer(invoke_without_command=True,
                          help=_tr("cli.process", _default="Supervise the agent's background processes: ps · log · kill · signal · wait."))
app.add_typer(process_app, name="process")

_PWS = typer.Option("workspaces/default", "--workspace", "-w", help=_tr("cli.process.workspace", _default="Agent workspace (where the processes live)."))
_PA = typer.Option(None, "--agent", "-a", help=_tr("cli.process.agent", _default="Agent (agents/<id>) — shortcut for its workspace."))


def _pm(workspace: str, agent: str | None):
    from okami.core.processes import ProcessManager
    from okami.home import agents_dir
    ws = (agents_dir() / agent) if agent else Path(workspace)
    return ProcessManager(ws)


def _process_table(pm) -> None:
    import time as _t
    procs = pm.list()
    if not procs:
        console.print("[dim]nenhum processo em background. (o agente sobe com process_start: servidor, build longo…)[/dim]")
        return
    t = Table(title="Processos em background", border_style="#ff7527", title_style="bold #ff7527")
    t.add_column("id", style="bold #f4f4f8", no_wrap=True)
    t.add_column("status", no_wrap=True)
    t.add_column("pid", style="#6c6d80", no_wrap=True)
    t.add_column("há", style="#6c6d80", no_wrap=True)
    t.add_column("comando", style="#b9bac8", overflow="ellipsis", max_width=54)
    now = _t.time()
    for p in procs:
        st = p.get("status", "?")
        color = {"running": "green", "exited": "#6c6d80", "unknown": "yellow"}.get(st, "white")
        code = p.get("exit_code")
        label = st + (f" ({code})" if st == "exited" and code is not None else "")
        if p.get("interactive"):
            label += " ·PTY"
        ago = f"{int(now - p['started'])}s" if p.get("started") else "?"
        t.add_row(p.get("id", ""), f"[{color}]{label}[/{color}]", str(p.get("pid", "")), ago, p.get("cmd", ""))
    console.print(t)


@process_app.callback(invoke_without_command=True)
def _process_main(ctx: typer.Context, workspace: str = _PWS, agent: str = _PA) -> None:
    """`okami process` sem subcomando → lista (= okami ps)."""
    if ctx.invoked_subcommand is None:
        _process_table(_pm(workspace, agent))


@process_app.command("list", help=_tr("cli.process.list", _default="List the agent's background processes (id · status · pid · command)."))
def process_list(workspace: str = _PWS, agent: str = _PA) -> None:
    """Lista os processos em background do agente (id · status · pid · comando)."""
    _process_table(_pm(workspace, agent))


@app.command(help=_tr("cli.ps", _default="Shortcut: list the agent's background processes (= okami process list)."))
def ps(workspace: str = _PWS, agent: str = _PA) -> None:
    """Atalho: lista os processos em background do agente (= okami process list)."""
    _process_table(_pm(workspace, agent))


@process_app.command("log", help=_tr("cli.process.log", _default="Show (or follow) a process log — redacted (secrets masked)."))
def process_log(
    pid_id: str = typer.Argument(..., help=_tr("cli.process.log.pid_id", _default="Process id (from okami ps).")),
    workspace: str = _PWS,
    agent: str = _PA,
    lines: int = typer.Option(200, "-n", "--lines", help=_tr("cli.process.log.lines", _default="How many trailing lines.")),
    follow: bool = typer.Option(False, "-f", "--follow", help=_tr("cli.process.log.follow", _default="Follow the log live (tail -f).")),
) -> None:
    """Mostra (ou segue) o log de um processo — redigido (segredo mascarado)."""
    import time as _t
    pm = _pm(workspace, agent)
    page = pm.log_page(pid_id, offset=-lines, limit=lines)
    if not page["total"]:
        console.print(f"[dim]sem log p/ #{pid_id} (id inexistente ou ainda sem saída).[/dim]")
        return
    for ln in page["lines"]:
        console.print(ln, markup=False)
    if not follow:
        return
    seen = page["total"]
    try:
        while True:
            nxt = pm.log_page(pid_id, offset=seen, limit=500)
            for ln in nxt["lines"]:
                console.print(ln, markup=False)
            seen += nxt["shown"]
            if pm.poll(pid_id).get("status") != "running" and nxt["shown"] == 0:
                break
            _t.sleep(0.4)
    except KeyboardInterrupt:
        return


@process_app.command("kill", help=_tr("cli.process.kill", _default="Kill the process (SIGTERM on the group · docker kill if isolated)."))
def process_kill(
    pid_id: str = typer.Argument(..., help=_tr("cli.process.kill.pid_id", _default="Process id.")),
    workspace: str = _PWS,
    agent: str = _PA,
) -> None:
    """Mata o processo (SIGTERM no grupo · docker kill se isolado)."""
    ok = _pm(workspace, agent).kill(pid_id)
    console.print(f"[yellow]⏹ #{pid_id} morto[/yellow]" if ok else f"[red]✗ #{pid_id} não encontrado[/red]")
    if not ok:
        raise typer.Exit(1)


@process_app.command("signal", help=_tr("cli.process.signal", _default="Send an arbitrary signal to the process group."))
def process_signal(
    pid_id: str = typer.Argument(..., help=_tr("cli.process.signal.pid_id", _default="Process id.")),
    sig: str = typer.Argument("TERM", help=_tr("cli.process.signal.sig", _default="Signal: TERM·INT·HUP·KILL·USR1·USR2·STOP·CONT·QUIT.")),
    workspace: str = _PWS,
    agent: str = _PA,
) -> None:
    """Manda um sinal arbitrário pro grupo do processo."""
    ok = _pm(workspace, agent).signal(pid_id, sig)
    console.print(f"[green]✓ {sig.upper()} → #{pid_id}[/green]" if ok else f"[red]✗ falhou (#{pid_id}/{sig})[/red]")
    if not ok:
        raise typer.Exit(1)


@process_app.command("wait", help=_tr("cli.process.wait", _default="Wait for the process to finish (up to timeout) and show the exit code."))
def process_wait(
    pid_id: str = typer.Argument(..., help=_tr("cli.process.wait.pid_id", _default="Process id.")),
    workspace: str = _PWS,
    agent: str = _PA,
    timeout: float = typer.Option(60.0, "-t", "--timeout"),
) -> None:
    """Espera o processo terminar (até timeout) e mostra o exit code."""
    st = _pm(workspace, agent).wait(pid_id, timeout=timeout)
    code = st.get("exit_code")
    if st.get("status") == "exited":
        console.print(f"[green]✓ #{pid_id} terminou[/green] [dim](exit {code})[/dim]")
    else:
        console.print(f"[yellow]⏳ #{pid_id} ainda {st.get('status')}[/yellow] (timeout {timeout}s)")


@process_app.command("clean", help=_tr("cli.process.clean", _default="Prune ALREADY-FINISHED processes (meta+log+exit) past the TTL."))
def process_clean(
    workspace: str = _PWS,
    agent: str = _PA,
    ttl_hours: float = typer.Option(24.0, "--ttl-hours", help=_tr("cli.process.clean.ttl_hours", _default="Remove those finished more than N hours ago.")),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Poda processos JÁ TERMINADOS (meta+log+exit) além do TTL."""
    removed = _pm(workspace, agent).prune(ttl_seconds=ttl_hours * 3600.0, dry_run=dry_run)
    verb = "seriam removidos" if dry_run else "removidos"
    console.print(f"[dim]{len(removed)} processo(s) {verb}.[/dim]")


@app.command("mcp", help=_tr("cli.mcp", _default="List MCP servers and their tools; `okami mcp auth <server>` does the OAuth/PKCE login."))
def mcp_cmd(
    auth: str = typer.Option("", "--auth", help=_tr("cli.mcp.auth", _default="OAuth-login (PKCE, browser) to an MCP server by name.")),
) -> None:
    """Lista os servidores MCP configurados e as tools que eles expõem. `--auth <server>`: login OAuth (#11)."""
    cfg = _load()
    servers = (cfg.mcp or {}).get("servers")
    if not servers:
        console.print("[dim]nenhum servidor MCP em okami.yaml (mcp.servers)[/dim]")
        return
    if auth:                                          # #11: login OAuth/PKCE no browser p/ MCP protegido
        from okami.home import okami_home
        from okami.integrations.mcp_oauth import TokenStore, authorize_interactive
        conf = servers.get(auth)
        if not conf:
            console.print(f"[red]servidor MCP '{auth}' não está em mcp.servers[/red]")
            raise typer.Exit(2)
        console.print(f"abrindo o browser p/ autorizar '{auth}' (OAuth/PKCE)…")
        ok = authorize_interactive(auth, conf, TokenStore(okami_home() / "mcp" / "oauth"))
        console.print(f"[green]✓ autorizado:[/green] {auth}" if ok
                      else f"[yellow]não autorizou {auth}[/yellow] [dim](precisa de mcp.servers.{auth}.oauth: "
                           "{authorization_endpoint, token_endpoint, client_id})[/dim]")
        return
    from okami.integrations.mcp import load_mcp_tools

    tools, clients = load_mcp_tools(servers, emit=lambda m: console.print(f"🔌 {m}"))
    table = Table(title="MCP tools")
    table.add_column("tool", style="bold")
    table.add_column("descrição")
    for name, t in tools.items():
        table.add_row(name, t.description[:70])
    console.print(table)
    for c in clients:
        c.close()


