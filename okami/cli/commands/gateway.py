"""Gateway/daemon: gateway · serve · room · heartbeat · route · mcp."""
from __future__ import annotations

import sys

import typer
from rich.table import Table
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load,
)


def _gateway_files() -> tuple[Path, Path]:
    d = Path(".okami")
    d.mkdir(parents=True, exist_ok=True)
    return d / "gateway.pid", d / "gateway.log"


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


@app.command()
def gateway(
    foreground: bool = typer.Option(False, "-f", "--foreground",
                                    help="Roda no terminal (logs ao vivo, Ctrl+C p/ sair)."),
    stop: bool = typer.Option(False, "--stop", help="Para o gateway que está em background."),
    status: bool = typer.Option(False, "--status", help="Mostra se o gateway está no ar."),
) -> None:
    """Sobe os bots de Telegram (1 por agente). Por padrão roda em BACKGROUND e te devolve o terminal;
    use -f p/ rodar em primeiro plano, --stop p/ parar, --status p/ checar."""
    import os
    import subprocess

    pidfile, logfile = _gateway_files()
    running_pid = int(pidfile.read_text()) if pidfile.exists() and pidfile.read_text().strip().isdigit() else None
    alive = running_pid is not None and _pid_alive(running_pid)

    if status:
        console.print(f"[green]● no ar[/green] (pid {running_pid}) · log: {logfile}" if alive
                      else "[dim]○ parado[/dim]")
        return
    if stop:
        if not alive:
            console.print("[dim]gateway não está rodando.[/dim]")
            pidfile.unlink(missing_ok=True)
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(running_pid)], capture_output=True)
        else:
            import signal
            os.kill(running_pid, signal.SIGTERM)
        pidfile.unlink(missing_ok=True)
        console.print(f"[yellow]⏹ gateway parado[/yellow] (pid {running_pid})")
        return

    from okami.agents import load_agents
    if not load_agents():
        console.print("[yellow]nenhum agente. Crie com: okami agent new <id>[/yellow]")
        raise typer.Exit(1)
    if alive and not foreground:
        console.print(f"[yellow]gateway já está no ar[/yellow] (pid {running_pid}). Pare com: okami gateway --stop")
        return

    if foreground:                                # primeiro plano: logs ao vivo, bloqueia (Ctrl+C)
        from okami.config import load_raw
        from okami.gateway import run_gateway
        graw, _ = load_raw()
        run_gateway(graw, load_agents(), emit=lambda m: console.print(f"🤖 {m}"))
        return

    # background (default): relança a si mesmo destacado e DEVOLVE o terminal
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
    console.print(f"[dim]logs:[/dim] {logfile}   [dim]status:[/dim] okami gateway --status   "
                  "[dim]parar:[/dim] okami gateway --stop")


@app.command()
def serve(
    port: int = typer.Option(8765, "-p", "--port"),
    host: str = typer.Option("127.0.0.1", "--host", help="127.0.0.1 (local) por padrão; 0.0.0.0 expõe à rede."),
) -> None:
    """Sobe a API HTTP (POST /chat com Bearer token). Requer OKAMI_API_TOKEN no .env (fail-closed)."""
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
        c, ws = (effective_config(graw, spec), spec.dir) if spec else (cfg, Path("workspaces/default"))
        ws.mkdir(parents=True, exist_ok=True)
        return _rt(c, ws, message)

    srv = _serve(port, token, run, host=host)
    console.print(f"[green]🌐 API no ar[/green] http://{host}:{port}  "
                  f"[dim](POST /chat · Authorization: Bearer …)[/dim]")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
        console.print("[dim]API parada.[/dim]")


@app.command()
def room(
    message: str = typer.Argument(..., help="Mensagem do usuário ao grupo (use @id para mencionar)."),
    group: int = typer.Option(0, "--group", "-g", help="Índice do grupo em okami.yaml (groups)."),
    provider: str = typer.Option(None, "--moderator", help="Provider barato p/ o moderador."),
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


@app.command()
def heartbeat(
    agent: str = typer.Option(None, "-a", "--agent", help="Agente Okami (workspace/config próprios) p/ executar."),
    workspace: str = typer.Option(".", "-w", "--workspace", help="Workspace (se não usar -a)."),
    mode: str = typer.Option("defer", "--mode", help="Governança das ações sensíveis: defer | yolo | off."),
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


@app.command()
def route(source: str = typer.Argument(..., help="Origem (ex.: telegram:12345) para rotear.")) -> None:
    """Mostra para qual agente uma origem é roteada (bindings §10)."""
    from okami.agents import build_router, load_agents

    cfg = _load()
    target = build_router(cfg.agents, load_agents()).route(source)
    console.print(f"{source} → [bold]{target or '(sem agente; defina agents.default)'}[/bold]")


@app.command("mcp")
def mcp_cmd() -> None:
    """Lista os servidores MCP configurados e as tools que eles expõem."""
    cfg = _load()
    servers = (cfg.mcp or {}).get("servers")
    if not servers:
        console.print("[dim]nenhum servidor MCP em okami.yaml (mcp.servers)[/dim]")
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


