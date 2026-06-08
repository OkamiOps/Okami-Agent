"""`okami curator` — consolida/arquiva as skills auto-criadas (tier lento, reversível). Estilo Hermes."""
from __future__ import annotations

import typer

from okami.cli._app import app, console
from okami.cli._shared import _load

curator_app = typer.Typer(invoke_without_command=True,
                          help="Curator das skills auto-criadas: arquiva sem-uso (LRU) + funde em umbrellas. "
                               "Nunca deleta (snapshot+rollback). Curadas/pinadas intocáveis.")
app.add_typer(curator_app, name="curator")


@curator_app.callback(invoke_without_command=True)
def curator_main(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, "--dry-run", help="Só reporta o que faria (não muta)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Não pergunta."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Só o archival determinístico (sem consolidação model-driven)."),
    archive_days: int = typer.Option(90, "--archive-days", help="Arquiva skill auto-criada sem uso há > N dias."),
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
    archived = cur.archive_unused(root, archive_days=archive_days)
    if archived:
        console.print(f"[green]📦 arquivadas {len(archived)}:[/green] {', '.join(archived)}")
    if not no_llm and n_agent:
        console.print("[dim]🧠 consolidação model-driven (funde estreitas em umbrellas)…[/dim]")
        cfg = _load()
        cur.run_consolidation(cfg, ".", root, emit=lambda m: console.print(f"[dim]{m}[/dim]"))
    console.print("[green]✓ curator concluído.[/green]")


@curator_app.command("schedule")
def curator_schedule(
    schedule: str = typer.Option("0 4 * * 0", "--schedule",
                                 help="cron 5-campos (default: domingo 04:00 = SEMANAL, como o Hermes)."),
    workspace: str = typer.Option(".", "-w", "--workspace"),
    remove: bool = typer.Option(False, "--remove", help="Remove o agendamento do curator."),
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


@curator_app.command("rollback")
def curator_rollback() -> None:
    """Desfaz a última passada do curator (restaura o snapshot mais recente)."""
    from okami.home import skills_dir
    from okami.learning import curator as cur
    restored = cur.rollback(skills_dir())
    console.print(f"[green]✓ restaurado de {restored.name}[/green]" if restored
                  else "[yellow]nenhum snapshot p/ restaurar.[/yellow]")


@curator_app.command("pin")
def curator_pin(name: str = typer.Argument(..., help="Skill a fixar (curator não toca).")) -> None:
    """Fixa uma skill — o curator nunca arquiva/funde ela."""
    from okami.home import skills_dir
    from okami.learning import curator as cur
    ok = cur.set_pinned(skills_dir(), name, True)
    console.print(f"[green]📌 {name} fixada[/green]" if ok else f"[red]✗ skill '{name}' não encontrada[/red]")


@curator_app.command("unpin")
def curator_unpin(name: str = typer.Argument(..., help="Skill a desafixar.")) -> None:
    """Tira o pin de uma skill (volta a ser curável)."""
    from okami.home import skills_dir
    from okami.learning import curator as cur
    ok = cur.set_pinned(skills_dir(), name, False)
    console.print(f"[green]📌 {name} desafixada[/green]" if ok else f"[red]✗ skill '{name}' não encontrada[/red]")
