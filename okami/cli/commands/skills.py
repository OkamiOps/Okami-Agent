"""Skills: skills · scan · learn (com quarentena + scan de risco)."""
from __future__ import annotations

import typer
from okami.i18n import t as _tr
from rich.table import Table
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _print_risk_report, _fetch_skill_source,
)


@app.command(help=_tr("cli.skills", _default="List skills (skills/*/SKILL.md). --prune removes low-value auto-distilled ones."))
def skills(
    prune: bool = typer.Option(False, "--prune", help=_tr("cli.skills.prune", _default="Prune low-value auto-distilled skills (auto_skill junk).")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_tr("cli.skills.dry_run", _default="With --prune: only list what would be removed (don't delete).")),
    yes: bool = typer.Option(False, "--yes", "-y", help=_tr("cli.skills.yes", _default="With --prune: remove without confirming.")),
    bad_names: bool = typer.Option(False, "--bad-names",
                                   help=_tr("cli.skills.bad_names", _default="With --prune: also prune bad conversational names (heuristic).")),
) -> None:
    """Lista as skills (skills/*/SKILL.md). `--prune` remove as auto-distiladas de baixo valor."""
    from okami import skills as skillmod
    from okami.home import skills_dir

    if prune:
        _prune_skills(skills_dir(), dry_run=dry_run, yes=yes, bad_names=bad_names)
        return
    sks = skillmod.load_skills(skills_dir())
    if not sks:
        console.print(f"[dim]nenhuma skill em {skills_dir()}[/dim]")
        return
    table = Table(title="Okami skills")
    table.add_column("nome", style="bold")
    table.add_column("triggers")
    table.add_column("descrição")
    for s in sks:
        auto = "  [dim]·auto[/dim]" if str(s.meta.get("origin", "")) == "auto-distilled" else ""
        table.add_row(s.name + auto, ", ".join(s.triggers[:5]), s.description[:60])
    console.print(table)
    if any(str(s.meta.get("origin", "")) == "auto-distilled" for s in sks):
        console.print("[dim]·auto = aprendida automaticamente. Limpe o lixo com: okami skills --prune[/dim]")


def _prune_skills(root, *, dry_run: bool, yes: bool, bad_names: bool) -> None:
    """Remove skills auto-distiladas de baixo valor (marcador origin OU assinatura do corpo antigo).
    Curadas/instaladas ficam intactas."""
    import shutil

    from okami import learning
    from okami import skills as skillmod

    sks = skillmod.load_skills(root)
    victims = [s for s in sks
               if learning.is_auto_distilled(s) or (bad_names and skillmod._name_is_bad(s.name))]
    if not victims:
        console.print(f"[green]✓ nada a podar[/green] [dim]({len(sks)} skills em {root}, todas curadas)[/dim]")
        return
    console.print(f"[yellow]{len(victims)} skill(s) auto-distilada(s) de baixo valor:[/yellow]")
    for s in victims:
        console.print(f"  • [bold]{s.name}[/bold]  [dim]{(s.description or '')[:64]}[/dim]")
    if dry_run:
        console.print("[dim]--dry-run: nada removido.[/dim]")
        return
    if not yes:
        from okami import menu
        if not menu.confirm(f"Remover {len(victims)} skill(s)?", default=False):
            console.print("[dim]cancelado.[/dim]")
            return
    removed = 0
    for s in victims:
        try:
            shutil.rmtree(s.path.parent)
            removed += 1
        except OSError as e:
            console.print(f"[red]falha em {s.name}: {e}[/red]")
    console.print(f"[green]✓ removidas {removed} skill(s).[/green] "
                  "[dim]o auto_skill agora só destila tarefa produtiva (não papo/exploração).[/dim]")


@app.command("skill", help=_tr("cli.skill_new", _default="Create a new skill: okami skill new <name> [--description --triggers --body]."))
def skill(
    action: str = typer.Argument(..., help=_tr("cli.skill.action", _default="Action (use: new).")),
    name: str = typer.Argument(..., help=_tr("cli.skill.name", _default="Skill name (kebab-case, short — a CLASS of task, not a phrase).")),
    description: str = typer.Option("", "--description", "-d", help=_tr("cli.skill.desc", _default="One-line description (≤120 chars).")),
    triggers: str = typer.Option("", "--triggers", "-t", help=_tr("cli.skill.triggers", _default="Comma-separated trigger keywords.")),
    body: str = typer.Option("", "--body", "-b", help=_tr("cli.skill.body", _default="Skill body in markdown (## Quando usar / ## Como / ## Cuidados). Omit to open $EDITOR.")),
) -> None:
    """Cria uma skill nova (humano). Valida nome, roda o scan de segurança e recusa conteúdo de risco."""
    import re as _re

    import yaml as _yaml
    from okami.home import skills_dir
    from okami.skills.skill_security import Severity, scan_text

    if action != "new":
        console.print(f"[red]ação '{action}' não reconhecida — use:[/red] okami skill new <nome>")
        raise typer.Exit(2)
    nm = name.strip().lower()
    if not _re.match(r"^[a-z0-9][a-z0-9._-]{1,47}$", nm) or nm.count("-") > 3:
        console.print("[red]nome inválido:[/red] kebab-case curto (≤48 chars, ≤3 hífens), nível de CLASSE "
                      "— não a frase do pedido. Ex.: `okami skill new deploy-flow`.")
        raise typer.Exit(2)
    root = skills_dir()
    f = root / nm / "SKILL.md"
    if f.exists():
        console.print(f"[red]skill '{nm}' já existe[/red] em {f} — edite o arquivo ou escolha outro nome.")
        raise typer.Exit(1)
    if not body.strip():                                  # sem --body → abre o editor (ou pede no stdin)
        tmpl = ("## Quando usar\n<em que situação esta skill se aplica>\n\n"
                "## Como\n<passo a passo do procedimento>\n\n## Cuidados\n<armadilhas/limites>\n")
        body = typer.edit(tmpl) or ""
    body = body.strip()
    if len(body) < 20:
        console.print("[red]corpo curto demais[/red] — descreva ## Quando usar / ## Como / ## Cuidados.")
        raise typer.Exit(2)
    findings = [f for f in scan_text(nm, body) if f.severity >= Severity.HIGH]
    if findings:
        console.print("[red]skill bloqueada pelo scan de segurança (HIGH)[/red] — reescreva sem o padrão de risco:")
        for fd in findings[:5]:
            console.print(f"  [yellow]·[/yellow] {fd.kind}: {fd.why}")
        raise typer.Exit(1)
    meta = {"name": nm, "description": (description.strip() or nm)[:120], "origin": "human"}
    trg = [s.strip().lower() for s in _re.split(r"[,;]", triggers) if s.strip()]
    if trg:
        meta["triggers"] = trg
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("---\n" + _yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + body + "\n",
                 encoding="utf-8", newline="\n")
    console.print(f"[green]✓ skill '{nm}' criada[/green] em {f}")
    console.print("[dim]revise o risco com:[/dim] okami scan " + str(f.parent))


@app.command(help=_tr("cli.scan", _default="Check a skill's risk (prompt injection, malware, secret exfiltration)."))
def scan(path: str = typer.Argument(..., help=_tr("cli.scan.path", _default="Skill directory/file to check."))) -> None:
    """Verifica risco de uma skill (prompt injection, malware, exfiltração de segredos)."""
    from okami.skills.skill_security import scan_path

    report = scan_path(Path(path))
    _print_risk_report(report)
    raise typer.Exit(2 if report.blocked else 0)


@app.command(help=_tr("cli.learn", _default="Download a skill, VALIDATE (quarantine + scan), then install into ./skills."))
def learn(
    source: str = typer.Argument(..., help=_tr("cli.learn.source", _default="owner/repo, URL, local path, or clawhub:<slug>.")),
    force: bool = typer.Option(False, "--force", help=_tr("cli.learn.force", _default="Install even if the scan BLOCKS (dangerous).")),
    allow_exec: bool = typer.Option(False, "--allow-exec",
                                    help=_tr("cli.learn.allow_exec", _default="Allow sources that EXECUTE code on fetch (clawhub/npx) BEFORE the scan.")),
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


