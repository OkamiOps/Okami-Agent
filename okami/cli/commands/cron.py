"""Automação e agentes: cron · hooks · agent."""
from __future__ import annotations

import typer
from okami.i18n import t as _tr
from rich.table import Table
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _ensure_agent,
)


cron_app = typer.Typer(invoke_without_command=True,
                       help=_tr("cli.cron", _default="Scheduling (§11): cron, intervals ('1h','every 30m'), one-shot (ISO)."))
app.add_typer(cron_app, name="cron")


@cron_app.callback(invoke_without_command=True)
def cron_main(ctx: typer.Context) -> None:
    """`okami cron` SEM subcomando → lista os jobs agendados."""
    if ctx.invoked_subcommand is None:
        cron_list(workspace=".")


def _cron_execute(job: dict, workspace: str):
    """Roda o prompt de um job pelo harness (no agente dele, se houver) e devolve o resultado."""
    from okami.runner import run_task

    if job.get("agent"):
        from okami.agents import effective_config, load_agents
        from okami.config import load_raw
        spec = load_agents().get(job["agent"])
        graw, _ = load_raw()
        cfg, ws = (effective_config(graw, spec), spec.dir) if spec else (_load(), Path(workspace))
    else:
        cfg, ws = _load(), Path(workspace)
    if job.get("action") == "curator":               # ação INTERNA: roda o curator (não um prompt do harness)
        from okami.home import skills_dir
        from okami.learning import curator as cur
        root = skills_dir()
        cur.snapshot(root)                           # reversível: snapshot antes de arquivar/consolidar
        archived = cur.archive_unused(root)
        # #9 review: usa o caminho CONTRACT-driven (apply_plan) — ele PRESERVA aliases na umbrella
        # (use_skill <nome-fundido> ainda resolve); o run_consolidation model-driven não gravava alias.
        cur.consolidate_with_contract(cfg, root, emit=lambda m: None)
        return f"curator: arquivadas {len(archived)} skills sem uso + consolidação rodada"
    t = run_task(cfg, ws, job["prompt"], emit=lambda m: None)
    return t.result or t.reason or t.state.value


@cron_app.command("add", help=_tr("cli.cron.add", _default="Schedule a task (persisted; the gateway wakes and runs it, or use `okami cron tick`)."))
def cron_add(
    schedule: str = typer.Argument(..., help=_tr("cli.cron.add.schedule", _default="cron (5 fields) | interval ('1h') | ISO ('2026-06-10T09:00').")),
    prompt: str = typer.Argument(..., help=_tr("cli.cron.add.prompt", _default="What the agent should do.")),
    agent: str = typer.Option(None, "-a", "--agent", help=_tr("cli.cron.add.agent", _default="Agent that runs it (default: global).")),
    to: str = typer.Option(None, "--to", help=_tr("cli.cron.add.to", _default="Destination chat for the result (gateway).")),
    gate: str = typer.Option(None, "--gate", help=_tr("cli.cron.add.gate", _default="Cheap shell pre-check: exit 0 wakes the agent; non-zero skips silently (no tokens).")),
    workspace: str = typer.Option(".", "-w", "--workspace"),
) -> None:
    """Agenda uma tarefa (persistida; o gateway acorda e executa, ou use `okami cron tick`)."""
    from okami.automation.scheduler import Scheduler

    job = Scheduler(workspace).add(schedule, prompt, agent=agent, target=to, gate=gate)
    extra = f" · gate=`{gate}`" if gate else ""
    console.print(f"[green]✓ job[/green] {job['id']} [{job['kind']}] · {schedule} → {prompt[:50]}{extra}")


@cron_app.command("list", help=_tr("cli.cron.list", _default="List scheduled jobs."))
def cron_list(workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Lista os jobs agendados."""
    from okami.automation.scheduler import Scheduler

    jobs = Scheduler(workspace).load()
    if not jobs:
        console.print("[dim]nenhum job. Crie com: okami cron add '1h' 'resumir o dia'[/dim]")
        return
    table = Table(title="Jobs agendados")
    for col in ("id", "schedule", "tipo", "on", "prompt"):
        table.add_column(col, style="bold" if col == "id" else None)
    for j in jobs:
        table.add_row(j["id"], j["schedule"], j.get("kind", "?"),
                      "✓" if j.get("enabled", True) else "✗", j["prompt"][:40])
    console.print(table)


@cron_app.command("remove", help=_tr("cli.cron.remove", _default="Remove a job."))
def cron_remove(job_id: str = typer.Argument(...),
                workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Remove um job."""
    from okami.automation.scheduler import Scheduler

    ok = Scheduler(workspace).remove(job_id)
    console.print(f"[green]✓ removido[/green] {job_id}" if ok else f"[yellow]não achei[/yellow] {job_id}")


@cron_app.command("run", help=_tr("cli.cron.run", _default="Run a job immediately (test)."))
def cron_run(job_id: str = typer.Argument(..., help=_tr("cli.cron.run.job_id", _default="Run a job NOW (ignores the schedule).")),
             workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Executa um job imediatamente (teste)."""
    from okami.automation.scheduler import Scheduler

    sched = Scheduler(workspace)
    job = next((j for j in sched.load() if j["id"] == job_id), None)
    if not job:
        console.print(f"[red]job '{job_id}' não encontrado[/red]")
        raise typer.Exit(1)
    console.print(f"[dim]rodando {job_id}…[/dim]")
    console.print(_cron_execute(job, workspace))
    sched.mark_run(job_id)


@cron_app.command("tick", help=_tr("cli.cron.tick", _default="Run all DUE jobs once (use with system cron / systemd timer)."))
def cron_tick(workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Roda todos os jobs VENCIDOS uma vez (use com o cron do sistema/systemd timer)."""
    from okami.automation.scheduler import Scheduler

    ran = Scheduler(workspace).tick(lambda job: _cron_execute(job, workspace))
    for jid, result in ran:
        console.print(f"[green]▶ {jid}[/green]: {str(result)[:200]}")
    if not ran:
        console.print("[dim]nada vencido agora.[/dim]")


suggestions_app = typer.Typer(invoke_without_command=True, help=_tr(
    "cli.suggestions", _default="Proactive automation suggestions (consent-first): list · accept · dismiss."))
app.add_typer(suggestions_app, name="suggestions")


@suggestions_app.callback(invoke_without_command=True)
def suggestions_main(ctx: typer.Context) -> None:
    """`okami suggestions` SEM subcomando → lista as sugestões pendentes."""
    if ctx.invoked_subcommand is None:
        suggestions_list(workspace=".")


@suggestions_app.command("list", help=_tr("cli.suggestions.list", _default="List pending automation suggestions."))
def suggestions_list(workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Lista as sugestões de automação pendentes (o agente propôs; você decide)."""
    from okami.automation.suggestions import SuggestionStore
    pend = SuggestionStore(workspace).pending()
    if not pend:
        console.print("[dim]nenhuma sugestão pendente.[/dim]")
        return
    for it in pend:
        console.print(f"[#ff7527]•[/] [bold]{it['id']}[/]  {it['text']}\n"
                      f"   [dim]{it['schedule']} → {it['prompt'][:70]}[/dim]")
    console.print("[dim]aceitar: okami suggestions accept <id>  ·  dispensar: okami suggestions dismiss <id>[/dim]")


@suggestions_app.command("accept", help=_tr("cli.suggestions.accept", _default="Accept a suggestion → schedules it as a cron job."))
def suggestions_accept(sid: str = typer.Argument(...),
                       workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Aceita uma sugestão → vira um cron job de verdade."""
    from okami.automation.scheduler import Scheduler
    from okami.automation.suggestions import SuggestionStore
    job = SuggestionStore(workspace).accept(sid, Scheduler(workspace))
    if not job:
        console.print(f"[red]sugestão '{sid}' não encontrada[/red] (veja: okami suggestions list)")
        raise typer.Exit(1)
    console.print(f"[green]✓ agendado[/green] {job['id']} · {job['schedule']} → {job['prompt'][:50]}")


@suggestions_app.command("dismiss", help=_tr("cli.suggestions.dismiss", _default="Dismiss a suggestion (won't be offered again)."))
def suggestions_dismiss(sid: str = typer.Argument(...),
                        workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Dispensa uma sugestão (não te ofereço de novo — latched)."""
    from okami.automation.suggestions import SuggestionStore
    ok = SuggestionStore(workspace).dismiss(sid)
    console.print(f"[dim]dispensada: {sid} — não te ofereço de novo.[/dim]" if ok
                  else f"[red]sugestão '{sid}' não encontrada[/red]")


@app.command("hooks", help=_tr("cli.hooks", _default="List the configured event hooks (§11)."))
def hooks_cmd(workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Lista os event hooks configurados (§11)."""
    from okami.automation.hooks import HookManager

    ev = HookManager(_load().hooks, root=workspace).events()
    if not ev:
        console.print("[dim]nenhum hook. Configure em okami.yaml (hooks:) ou crie hooks/<evento>/*.sh[/dim]")
        return
    for name, n in sorted(ev.items()):
        console.print(f"  [bold]{name}[/bold]: {n} hook(s)")


agent_app = typer.Typer(invoke_without_command=True,
                        help=_tr("cli.agent", _default="Multi-agent (§10): each agent has its own workspace/config/persona."))
app.add_typer(agent_app, name="agent")


@agent_app.callback(invoke_without_command=True)
def agent_main(ctx: typer.Context) -> None:
    """`okami agent` SEM subcomando → lista os agentes."""
    if ctx.invoked_subcommand is None:
        agent_list()


@agent_app.command("new", help=_tr("cli.agent.new", _default="Create an agent: <home>/agents/<id>/ with agent.yaml + its own identity."))
def agent_new(
    agent_id: str = typer.Argument(..., help=_tr("cli.agent.new.agent_id", _default="Agent ID (becomes agents/<id>/).")),
    name: str = typer.Option(None, "--name", help=_tr("cli.agent.new.name", _default="Name (default = id).")),
    provider: str = typer.Option(None, "--provider", help=_tr("cli.agent.new.provider", _default="Agent's default provider.")),
    memory: str = typer.Option(None, "--memory", help=_tr("cli.agent.new.memory", _default="Agent's memory backend.")),
    match: list[str] = typer.Option(None, "--match", help=_tr("cli.agent.new.match", _default="Binding (origin) to route to this agent.")),
    telegram_token: str = typer.Option(None, "--telegram-token", help=_tr("cli.agent.new.telegram_token", _default="Agent's Telegram bot token.")),
) -> None:
    """Cria um agente: <casa>/agents/<id>/ com agent.yaml + identidade própria."""
    from okami.home import agents_dir
    if (agents_dir() / agent_id / "agent.yaml").exists():
        console.print(f"[yellow]agente '{agent_id}' já existe.[/yellow]")
        raise typer.Exit(1)
    _ensure_agent(agent_id, name=name, provider=provider, memory=memory, match=match,
                  telegram_token=telegram_token)
    d = (agents_dir() / agent_id).resolve()
    console.print(f"[green]✓ agente '{agent_id}' criado[/green]\n[dim]   {d}[/dim]\n"
                  "[dim]   (NÃO confundir com okami/agents/ que é o código)[/dim]")


@agent_app.command("list", help=_tr("cli.agent.list", _default="List agents and their effective config (global + overrides)."))
def agent_list() -> None:
    """Lista os agentes e a config efetiva (global + overrides)."""
    from okami.agents import load_agents
    from okami.config import build_config, load_raw
    from okami.config import _deep_merge as _dm

    specs = load_agents()
    if not specs:
        console.print("[dim]nenhum agente (crie com: okami agent new <id>)[/dim]")
        return
    graw, _ = load_raw()
    default = (build_config(graw).agents or {}).get("default")
    from okami.home import agents_dir
    table = Table(title=f"Agentes  ·  pasta: {agents_dir().resolve()}")
    table.add_column("id", style="bold")
    table.add_column("provider")
    table.add_column("memória")
    table.add_column("bindings")
    for aid, spec in specs.items():
        try:
            eff = build_config(_dm(graw, spec.raw))
            prov, memb = eff.default_provider, str(eff.memory.get("backend", "sqlite-fts5"))
        except Exception:  # noqa: BLE001
            prov, memb = "?", "?"
        mark = aid + (" [cyan](default)[/cyan]" if aid == default else "")
        table.add_row(mark, prov, memb, ", ".join(spec.raw.get("match") or []) or "-")
    console.print(table)


@agent_app.command("up", help=_tr("cli.agent.up", _default="Spawn each agent as its OWN supervised gateway (bot/cron/heartbeat per agent)."))
def agent_up(
    agent_id: str = typer.Argument(None, help=_tr("cli.agent.up.id", _default="One agent (default: all configured agents).")),
) -> None:
    """Sobe cada agente como SEU PRÓPRIO gateway supervisionado (Telegram/cron/heartbeat isolados)."""
    from okami.gateway.supervisor import AgentSupervisor
    s = AgentSupervisor()
    res = [s.spawn(agent_id)] if agent_id else s.up()
    if not res:
        console.print("[yellow]nenhum agente. Crie com: okami agent new <id>[/yellow]")
        raise typer.Exit(1)
    for r in res:
        console.print(f"[green]●[/green] {r['id']} " + ("(já no ar)" if r.get("already") else f"subiu (pid {r.get('pid')})"))


@agent_app.command("down", help=_tr("cli.agent.down", _default="Stop the supervised gateways of all agents."))
def agent_down(
    agent_id: str = typer.Argument(None, help=_tr("cli.agent.down.id", _default="One agent (default: all running).")),
) -> None:
    from okami.gateway.supervisor import AgentSupervisor
    s = AgentSupervisor()
    if agent_id:
        console.print(("[dim]parado[/dim] " if s.stop(agent_id) else "[yellow]não estava no ar:[/yellow] ") + agent_id)
        return
    for r in s.down():
        console.print(("[dim]parado[/dim] " if r["stopped"] else "[yellow]?[/yellow] ") + r["id"])


@agent_app.command("status", help=_tr("cli.agent.status", _default="Show which agents' gateways are alive."))
def agent_status() -> None:
    from okami.gateway.supervisor import AgentSupervisor
    rows = AgentSupervisor().status()
    if not rows:
        console.print("[dim]nenhum agente configurado.[/dim]")
        return
    table = Table(title="Agentes — gateways")
    table.add_column("id", style="bold")
    table.add_column("estado")
    table.add_column("pid")
    table.add_column("uptime")
    for r in rows:
        up = f"{r['uptime_s'] // 60}m" if r.get("uptime_s") else "-"
        table.add_row(r["id"], "[green]● no ar[/green]" if r["alive"] else "[dim]○ parado[/dim]",
                      str(r.get("pid") or "-"), up)
    console.print(table)


@agent_app.command("supervise", help=_tr("cli.agent.supervise", _default="Watchdog loop: respawn any agent whose gateway dies (Ctrl+C to stop)."))
def agent_supervise(
    interval: float = typer.Option(30.0, "--interval", help=_tr("cli.agent.supervise.interval", _default="Seconds between health checks.")),
) -> None:
    """Watchdog: ressobe qualquer agente cujo gateway cair. Ctrl+C para sair."""
    from okami.gateway.supervisor import AgentSupervisor
    s = AgentSupervisor()
    console.print(f"[green]🐕 watchdog ativo[/green] (checa a cada {int(interval)}s · Ctrl+C sai)")
    s.up()
    try:
        s.supervise(interval=interval)
    except KeyboardInterrupt:
        console.print("\n[dim]watchdog encerrado (os gateways seguem no ar — okami agent down p/ parar).[/dim]")


