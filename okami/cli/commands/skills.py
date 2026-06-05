"""Skills: skills · scan · learn (com quarentena + scan de risco)."""
from __future__ import annotations

import typer
from rich.table import Table
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _print_risk_report, _fetch_skill_source,
)


@app.command()
def skills() -> None:
    """Lista as skills disponíveis (skills/*/SKILL.md)."""
    from okami import skills as skillmod
    from okami.home import skills_dir

    sks = skillmod.load_skills(skills_dir())
    if not sks:
        console.print(f"[dim]nenhuma skill em {skills_dir()}[/dim]")
        return
    table = Table(title="Okami skills")
    table.add_column("nome", style="bold")
    table.add_column("triggers")
    table.add_column("descrição")
    for s in sks:
        table.add_row(s.name, ", ".join(s.triggers[:5]), s.description[:60])
    console.print(table)


@app.command()
def scan(path: str = typer.Argument(..., help="Diretório/arquivo de skill a verificar.")) -> None:
    """Verifica risco de uma skill (prompt injection, malware, exfiltração de segredos)."""
    from okami.skills.skill_security import scan_path

    report = scan_path(Path(path))
    _print_risk_report(report)
    raise typer.Exit(2 if report.blocked else 0)


@app.command()
def learn(
    source: str = typer.Argument(..., help="owner/repo, URL, caminho local, ou clawhub:<slug>."),
    force: bool = typer.Option(False, "--force", help="Instalar mesmo se o scan BLOQUEAR (perigoso)."),
    allow_exec: bool = typer.Option(False, "--allow-exec",
                                    help="Permite fontes que EXECUTAM código no fetch (clawhub/npx) ANTES do scan."),
) -> None:
    """Baixa uma skill, VALIDA (quarentena + scan) e só então instala em ./skills (skill.sh/ClawHub)."""
    import shutil

    from okami import skills as skillmod
    from okami.skills.skill_security import scan_path

    if source.startswith("clawhub:") and not allow_exec:    # P1.5: clawhub roda npx ANTES do scan validar
        console.print("[red]✗ clawhub roda `npx` (código do ecossistema npm) ANTES do scan validar.[/red]")
        console.print("[dim]use --allow-exec se confiar na origem; prefira git/caminho local (estáticos).[/dim]")
        raise typer.Exit(2)

    from okami.home import okami_home
    quarantine = okami_home() / "quarantine"           # na CASA, não espalha .okami no CWD
    shutil.rmtree(quarantine, ignore_errors=True)
    console.print(f"[dim]baixando para quarentena:[/dim] {quarantine}")
    try:
        _fetch_skill_source(source, quarantine)
    except FileNotFoundError as e:
        console.print(f"[red]ferramenta ausente ({e}).[/red] Precisa de git (ou npx p/ clawhub).")
        raise typer.Exit(1)

    found = skillmod.load_skills(quarantine)
    if not found:
        console.print("[yellow]nenhuma SKILL.md encontrada na fonte.[/yellow]")
        raise typer.Exit(1)
    console.print(f"[dim]skills encontradas:[/dim] {', '.join(s.name for s in found)}")

    report = scan_path(quarantine)
    _print_risk_report(report)
    if report.blocked and not force:
        console.print("[red]✗ BLOQUEADO — risco HIGH/CRITICAL.[/red] Revise os achados acima.")
        console.print(f"[dim]ficou em quarentena (não instalado): {quarantine}[/dim]")
        console.print("[dim]use --force só se confiar TOTALMENTE na origem.[/dim]")
        raise typer.Exit(2)
    if report.blocked:
        console.print("[red]⚠ --force: instalando apesar do risco.[/red]")

    from okami.home import skills_dir
    dest_root = skills_dir()
    dest_root.mkdir(parents=True, exist_ok=True)
    from okami.skills.lockfile import record
    promoted = []
    for s in found:
        target = dest_root / s.path.parent.name
        shutil.copytree(s.path.parent, target, dirs_exist_ok=True)
        record(Path("."), s.name, source=source, skill_dir=target)   # proveniência + sha256 (P1.5)
        promoted.append(s.name)
    shutil.rmtree(quarantine, ignore_errors=True)
    console.print(f"[green]✓ instaladas:[/green] {', '.join(promoted)} [dim](🔒 skills-lock.json)[/dim]")


