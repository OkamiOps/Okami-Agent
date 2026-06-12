"""`okami curator` — consolida/arquiva as skills auto-criadas (tier lento, reversível). Estilo Hermes."""
from __future__ import annotations

import typer
from okami.i18n import t as _tr

from okami.cli._app import app, console
from okami.cli._shared import _load

curator_app = typer.Typer(invoke_without_command=True,
                          help=_tr("cli.curator", _default="Curator for auto-created skills: archive unused (LRU) + merge into umbrellas. "
                                   "Never deletes (snapshot+rollback). Curated/pinned are untouchable."))
app.add_typer(curator_app, name="curator")


@curator_app.callback(invoke_without_command=True)
def curator_main(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, "--dry-run", help=_tr("cli.curator.dry_run", _default="Only report what it would do (no mutation).")),
    yes: bool = typer.Option(False, "--yes", "-y", help=_tr("cli.curator.yes", _default="Don't ask.")),
    no_llm: bool = typer.Option(False, "--no-llm", help=_tr("cli.curator.no_llm", _default="Deterministic archival only (no model-driven consolidation).")),
    archive_days: int = typer.Option(90, "--archive-days", help=_tr("cli.curator.archive_days", _default="Archive auto-created skill unused for > N days.")),
    stale_days: int = typer.Option(30, "--stale-days", help=_tr("cli.curator.stale_days", _default="Mark auto-created skill unused for > N days as STALE (persisted state).")),
) -> None:
    """Roda o curator (sem subcomando). Use `okami curator rollback` p/ desfazer a última passada."""
    if ctx.invoked_subcommand is not None:
        return
    from okami.home import skills_dir
    from okami.learning import curator as cur
    root = skills_dir()

    cands = cur.archival_candidates(root, archive_days=archive_days)
    digest = cur.agent_skill_digest(root)
    n_agent = 0 if digest == "(nenhuma)" else len(digest.splitlines())
    console.print(f"[dim]{root}[/dim] · skills auto-criadas: {n_agent} · candidatas a arquivar (sem uso "
                  f">{archive_days}d): {len(cands)}")
    for c in cands:
        console.print(f"  📦 arquivaria: [bold]{c}[/bold]")
    if dry_run:
        console.print("[dim]--dry-run: nada mutado.[/dim]")
        if not no_llm and n_agent:
            console.print("[dim](a consolidação model-driven roda na passada real, sem --dry-run)[/dim]")
        return
    if not yes and (cands or (not no_llm and n_agent)):
        from okami import menu
        if not menu.confirm("Rodar o curator (snapshot antes; reversível com rollback)?", default=False):
            console.print("[dim]cancelado.[/dim]")
            return
    snap = cur.snapshot(root)
    if snap:
        console.print(f"[dim]📸 snapshot: {snap.name} (rollback: okami curator rollback)[/dim]")
    # Lifecycle SEM LLM (pesquisa #5 item 44): 30d→STALE (persistido no .usage.json), 90d→archive.
    life = cur.lifecycle_pass(root, stale_days=stale_days, archive_days=archive_days)
    if life["stale"]:
        console.print(f"[yellow]💤 stale ({stale_days}d sem uso):[/yellow] {', '.join(life['stale'])}")
    if life["archived"]:
        console.print(f"[green]📦 arquivadas {len(life['archived'])}:[/green] {', '.join(life['archived'])}")
    if not no_llm and n_agent:
        console.print("[dim]🧠 consolidação model-driven (plano YAML validado por contrato)…[/dim]")
        cfg = _load()
        out = cur.consolidate_with_contract(cfg, root, emit=lambda m: console.print(f"[dim]{m}[/dim]"))
        if out["applied"]:
            s = out["summary"]
            console.print(f"[green]🧩 umbrellas: {', '.join(s['created']) or '—'} · "
                          f"absorvidas/arquivadas: {len(s['archived'])}[/green]")
        elif out["errors"]:
            console.print("[yellow]plano reprovado no contrato — nada mudou (fail-closed).[/yellow]")
    console.print("[green]✓ curator concluído.[/green]")


@curator_app.command("schedule", help=_tr("cli.curator.schedule", _default="Schedule the curator to run on its own (weekly). The gateway wakes and runs it (or `okami cron tick`)."))
def curator_schedule(
    schedule: str = typer.Option("0 4 * * 0", "--schedule",
                                 help=_tr("cli.curator.schedule.schedule", _default="cron 5-field (default: Sunday 04:00 = WEEKLY, like Hermes).")),
    workspace: str = typer.Option(".", "-w", "--workspace"),
    remove: bool = typer.Option(False, "--remove", help=_tr("cli.curator.schedule.remove", _default="Remove the curator's schedule.")),
) -> None:
    """Agenda o curator pra rodar SOZINHO (semanal). O gateway acorda e executa (ou `okami cron tick`)."""
    from okami.automation.scheduler import Scheduler
    sch = Scheduler(workspace)
    for j in sch.load():                             # idempotente: tira o agendamento anterior do curator
        if j.get("action") == "curator":
            sch.remove(j["id"])
    if remove:
        console.print("[green]✓ agendamento do curator removido.[/green]")
        return
    job = sch.add(schedule, "curator: consolida/arquiva skills auto-criadas", action="curator")
    console.print(f"[green]✓ curator agendado[/green] [bold]{job['id']}[/bold] · {schedule} "
                  "[dim](semanal). Roda pelo gateway, ou force com: okami cron tick.[/dim]")


@curator_app.command("rollback", help=_tr("cli.curator.rollback", _default="Undo the curator's last pass (restore the most recent snapshot)."))
def curator_rollback() -> None:
    """Desfaz a última passada do curator (restaura o snapshot mais recente)."""
    from okami.home import skills_dir
    from okami.learning import curator as cur
    restored = cur.rollback(skills_dir())
    console.print(f"[green]✓ restaurado de {restored.name}[/green]" if restored
                  else "[yellow]nenhum snapshot p/ restaurar.[/yellow]")


@curator_app.command("pin", help=_tr("cli.curator.pin", _default="Pin a skill — the curator never archives/merges it."))
def curator_pin(name: str = typer.Argument(..., help=_tr("cli.curator.pin.name", _default="Skill to pin (curator won't touch)."))) -> None:
    """Fixa uma skill — o curator nunca arquiva/funde ela."""
    from okami.home import skills_dir
    from okami.learning import curator as cur
    ok = cur.set_pinned(skills_dir(), name, True)
    console.print(f"[green]📌 {name} fixada[/green]" if ok else f"[red]✗ skill '{name}' não encontrada[/red]")


@curator_app.command("unpin", help=_tr("cli.curator.unpin", _default="Unpin a skill (it becomes curable again)."))
def curator_unpin(name: str = typer.Argument(..., help=_tr("cli.curator.unpin.name", _default="Skill to unpin."))) -> None:
    """Tira o pin de uma skill (volta a ser curável)."""
    from okami.home import skills_dir
    from okami.learning import curator as cur
    ok = cur.set_pinned(skills_dir(), name, False)
    console.print(f"[green]📌 {name} desafixada[/green]" if ok else f"[red]✗ skill '{name}' não encontrada[/red]")
