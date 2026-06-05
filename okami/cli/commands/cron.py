"""Automação e agentes: cron · hooks · agent."""
from __future__ import annotations

import typer
from rich.table import Table
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _ensure_agent,
)


cron_app = typer.Typer(invoke_without_command=True,
                       help="Scheduling (§11): cron, intervalos ('1h','every 30m'), one-shot (ISO).")
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
    t = run_task(cfg, ws, job["prompt"], emit=lambda m: None)
    return t.result or t.reason or t.state.value


@cron_app.command("add")
def cron_add(
    schedule: str = typer.Argument(..., help="cron (5 campos) | intervalo ('1h') | ISO ('2026-06-10T09:00')."),
    prompt: str = typer.Argument(..., help="O que o agente deve fazer."),
    agent: str = typer.Option(None, "-a", "--agent", help="Agente que executa (default: global)."),
    to: str = typer.Option(None, "--to", help="Chat de destino do resultado (gateway)."),
    workspace: str = typer.Option(".", "-w", "--workspace"),
) -> None:
    """Agenda uma tarefa (persistida; o gateway acorda e executa, ou use `okami cron tick`)."""
    from okami.automation.scheduler import Scheduler

    job = Scheduler(workspace).add(schedule, prompt, agent=agent, target=to)
    console.print(f"[green]✓ job[/green] {job['id']} [{job['kind']}] · {schedule} → {prompt[:50]}")


@cron_app.command("list")
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


@cron_app.command("remove")
def cron_remove(job_id: str = typer.Argument(...),
                workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Remove um job."""
    from okami.automation.scheduler import Scheduler

    ok = Scheduler(workspace).remove(job_id)
    console.print(f"[green]✓ removido[/green] {job_id}" if ok else f"[yellow]não achei[/yellow] {job_id}")


@cron_app.command("run")
def cron_run(job_id: str = typer.Argument(..., help="Roda um job AGORA (ignora o schedule)."),
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


@cron_app.command("tick")
def cron_tick(workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Roda todos os jobs VENCIDOS uma vez (use com o cron do sistema/systemd timer)."""
    from okami.automation.scheduler import Scheduler

    ran = Scheduler(workspace).tick(lambda job: _cron_execute(job, workspace))
    for jid, result in ran:
        console.print(f"[green]▶ {jid}[/green]: {str(result)[:200]}")
    if not ran:
        console.print("[dim]nada vencido agora.[/dim]")


@app.command("hooks")
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
                        help="Multi-agente (§10): cada agente tem workspace/config/persona próprios.")
app.add_typer(agent_app, name="agent")


@agent_app.callback(invoke_without_command=True)
def agent_main(ctx: typer.Context) -> None:
    """`okami agent` SEM subcomando → lista os agentes."""
    if ctx.invoked_subcommand is None:
        agent_list()


@agent_app.command("new")
def agent_new(
    agent_id: str = typer.Argument(..., help="ID do agente (vira agents/<id>/)."),
    name: str = typer.Option(None, "--name", help="Nome (default = id)."),
    provider: str = typer.Option(None, "--provider", help="Provider default do agente."),
    memory: str = typer.Option(None, "--memory", help="Backend de memória do agente."),
    match: list[str] = typer.Option(None, "--match", help="Binding (origem) p/ rotear a este agente."),
    telegram_token: str = typer.Option(None, "--telegram-token", help="Token do bot Telegram do agente."),
) -> None:
    """Cria um agente: agents/<id>/ com agent.yaml + identidade própria."""
    if (Path("agents") / agent_id / "agent.yaml").exists():
        console.print(f"[yellow]agente '{agent_id}' já existe.[/yellow]")
        raise typer.Exit(1)
    _ensure_agent(agent_id, name=name, provider=provider, memory=memory, match=match,
                  telegram_token=telegram_token)
    d = (Path("agents") / agent_id).resolve()
    console.print(f"[green]✓ agente '{agent_id}' criado[/green]\n[dim]   {d}[/dim]\n"
                  "[dim]   (NÃO confundir com okami/agents/ que é o código)[/dim]")


@agent_app.command("list")
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
    table = Table(title=f"Agentes  ·  pasta: {Path('agents').resolve()}")
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


