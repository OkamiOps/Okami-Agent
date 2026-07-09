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


def _skill_hub_action(action: str, name: str) -> None:
    """list/verify/remove das skills instaladas (proveniência via skills-lock.json)."""
    from okami.home import skills_dir
    from okami.skills import hub
    lock_root = Path(".")                                 # mesmo lugar que `okami learn` grava o lock
    sk_root = skills_dir()
    items = hub.installed(lock_root, sk_root)
    if action == "list":
        if not items:
            console.print("[dim]nenhuma skill com proveniência registrada (instale com `okami learn`).[/dim]")
            return
        table = Table(title="Skills instaladas")
        table.add_column("nome", style="bold")
        table.add_column("origem")
        table.add_column("versão")
        table.add_column("íntegra")
        for it in items:
            mark = "[green]✓[/green]" if it["ok"] else ("[red]ausente[/red]" if not it["present"]
                                                        else "[red]✗ adulterada[/red]")
            table.add_row(it["name"], it["source"] or "—", it["version"] or "—", mark)
        console.print(table)
        return
    if action == "verify":
        bad = [it["name"] for it in items if not it["ok"]]
        if bad:
            console.print(f"[red]✗ {len(bad)} skill(s) com problema:[/red] {', '.join(bad)}")
            raise typer.Exit(1)
        console.print(f"[green]✓ {len(items)} skill(s) íntegra(s).[/green]")
        return
    if action == "remove":
        if not name.strip():
            console.print("[red]informe o nome:[/red] okami skill remove <nome>")
            raise typer.Exit(2)
        if hub.remove(lock_root, sk_root, name.strip()):
            console.print(f"[green]✓ skill '{name.strip()}' removida[/green] (pasta + lockfile).")
        else:
            console.print(f"[yellow]skill '{name.strip()}' não estava instalada.[/yellow]")
        return


def _skill_discover_action(action: str, query: str, *, as_json: bool, do_install: bool) -> None:
    """`okami skill search <query>` / `okami skill browse` — DESCOBRE skills no catálogo GitHub
    confiável (okami.skills.registry) e, se pedido, instala pela pipeline EXISTENTE (`learn`/
    `install_from_source` — quarentena+scan+lockfile inalterados)."""
    import json as _json

    from okami.skills.registry import default_source

    src = default_source()
    try:
        cands = src.search(query, 20) if action == "search" else src.browse(20)
    except Exception as e:  # noqa: BLE001 — descoberta nunca deve derrubar o CLI
        console.print(f"[red]falha ao consultar o catálogo:[/red] {e}")
        raise typer.Exit(1)

    if as_json:
        console.print(_json.dumps([c.__dict__ for c in cands], ensure_ascii=False, indent=2))
        return
    if not cands:
        hint = f" p/ '{query}'" if query else ""
        console.print(f"[dim]nenhuma skill encontrada{hint} nos taps confiáveis.[/dim] "
                      "[dim]amplie com: okami skill tap github <org>[/dim]")
        return

    table = Table(title="Skills catalog" if action == "browse" else f"Skills catalog — busca '{query}'")
    table.add_column("#", justify="right")
    table.add_column("nome", style="bold")
    table.add_column("descrição")
    table.add_column("fonte")
    table.add_column("confiança")
    for i, c in enumerate(cands, 1):
        table.add_row(str(i), c.name, c.description[:70], c.source, c.trust)
    console.print(table)
    console.print("[dim]instale com: okami learn <fonte> --name <apenas-esta>[/dim]" if not do_install else "")

    if not do_install:
        return
    chosen = cands[0]
    console.print(f"[dim]instalando #1: {chosen.name} ({chosen.source})…[/dim]")
    from okami.home import skills_dir
    from okami.skills.install import install_from_source
    res = install_from_source(chosen.source, skills_dir(), Path("."),
                              only=chosen.only, confirm=True)
    if res.ok:
        console.print(f"[green]✓ instalada:[/green] {', '.join(res.installed)}")
        if res.reason:
            console.print(f"[yellow]{res.reason}[/yellow]")
    else:
        console.print(f"[red]✗ falha:[/red] {res.reason}")
        raise typer.Exit(1)


@app.command("skill", help=_tr("cli.skill_cmd", _default="Manage skills: okami skill new|list|verify|remove [name]."))
def skill(
    action: str = typer.Argument(..., help=_tr("cli.skill.action", _default="new | list | verify | remove.")),
    name: str = typer.Argument("", help=_tr("cli.skill.name", _default="Skill name (kebab-case; not needed for list).")),
    description: str = typer.Option("", "--description", "-d", help=_tr("cli.skill.desc", _default="One-line description (≤120 chars).")),
    triggers: str = typer.Option("", "--triggers", "-t", help=_tr("cli.skill.triggers", _default="Comma-separated trigger keywords.")),
    body: str = typer.Option("", "--body", "-b", help=_tr("cli.skill.body", _default="Skill body in markdown (## Quando usar / ## Como / ## Cuidados). Omit to open $EDITOR.")),
    as_json: bool = typer.Option(False, "--json", help=_tr("cli.skill.json", _default="With search/browse: print raw JSON instead of a table.")),
    install: bool = typer.Option(False, "--install", help=_tr("cli.skill.install", _default="With search/browse: install the first result right away (no picker).")),
) -> None:
    """Gerencia skills: new (criar), list (instaladas + proveniência), verify (integridade), remove,
    search/browse (descobrir no catálogo GitHub confiável — item 11.5, o gap 'não sei o owner/repo')."""
    import re as _re

    import yaml as _yaml
    from okami.home import skills_dir
    from okami.skills.skill_security import Severity, scan_text

    if action in ("list", "verify", "remove"):
        _skill_hub_action(action, name)
        return
    if action in ("tap", "taps"):                    # gerenciar fontes confiáveis (item 11)
        from okami.skills.sources import add_tap, list_taps, remove_tap
        # `okami skill tap` lista; `tap <org>` / `tap github <org>` adiciona; `tap remove <org>`
        if not name:
            taps = list_taps()
            if not taps:
                console.print("[dim]nenhum tap customizado. Confiáveis embutidos: anthropics, openai, "
                              "nousresearch, huggingface, okamiops.[/dim]")
            for kind, lst in taps.items():
                console.print(f"[bold]{kind}[/bold]: {', '.join(lst) or '—'}")
            return
        parts = name.split()
        if parts[0] == "remove" and len(parts) > 1:
            ok = remove_tap("github", parts[-1])
            console.print(f"[green]✓ tap removido:[/green] {parts[-1]}" if ok else "[yellow]tap não existia.[/yellow]")
            return
        kind, prefix = ("github", parts[0]) if len(parts) == 1 else (parts[0], parts[1])
        add_tap(kind, prefix)
        console.print(f"[green]✓ fonte confiável adicionada:[/green] {kind}:{prefix} "
                      "[dim](skills dela instalam sem confirmar, se o scan passar)[/dim]")
        return
    if action == "config":                           # #11: config que as skills declaram no frontmatter
        from okami import skills as _sk
        decl = _sk.discover_all_skill_config_vars(_sk.load_skills(skills_dir()))
        if not decl:
            console.print("[dim]nenhuma skill declara config (metadata.okami.config).[/dim]")
            return
        for c in decl:
            console.print(f"[bold]{c['key']}[/bold] [dim](skill: {c['skill']})[/dim] — {c['description']}")
        return
    if action == "bundle":                           # #11: dispatch de bundle — UM nome carrega N skills
        from okami import skills as _sk
        from okami.skills.bundles import bundle_invocation_message, resolve_bundle
        if not name:
            from okami.skills.bundles import list_bundles
            avail = list_bundles(skills_dir() / "bundles")
            console.print("bundles: " + (", ".join(avail) if avail else "[dim]nenhum[/dim]"))
            return
        root = skills_dir()
        resolved = resolve_bundle(root / "bundles", name, _sk.load_skills(root))
        if not resolved:
            console.print(f"[yellow]bundle '{name}' vazio ou inexistente[/yellow] [dim]({root / 'bundles'})[/dim]")
            raise typer.Exit(1)
        console.print(bundle_invocation_message(name, resolved))
        return
    if action in ("search", "browse"):
        _skill_discover_action(action, name, as_json=as_json, do_install=install)
        return
    if action != "new":
        console.print(f"[red]ação '{action}' não reconhecida — use:[/red] new | list | verify | remove | tap | bundle | config | search | browse")
        raise typer.Exit(2)
    if not name.strip():
        console.print("[red]informe o nome:[/red] okami skill new <nome>")
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
    # MATRIZ confiança×verdict (item 11): combina o TIER da fonte com o achado do scan.
    from okami.skills.skill_security import SEV_NAME
    from okami.skills.sources import classify_source, install_decision
    src_info = classify_source(source)
    verdict = SEV_NAME[report.max_severity]
    decision = install_decision(src_info.trust, verdict)
    console.print(f"[dim]fonte: {src_info.kind} · confiança: [bold]{src_info.trust}[/bold] · "
                  f"scan: {verdict} → política: [bold]{decision}[/bold][/dim]")
    if decision == "block" and not force:
        console.print("[red]✗ BLOQUEADO — risco HIGH/CRITICAL (segurança vence confiança).[/red]")
        console.print(f"[dim]ficou em quarentena (não instalado): {quarantine}[/dim]")
        console.print("[dim]use --force só se confiar TOTALMENTE na origem.[/dim]")
        raise typer.Exit(2)
    if decision == "block":
        console.print("[red]⚠ --force: instalando apesar do risco.[/red]")
    elif decision == "confirm" and not force:        # fonte comunidade/não-confiável → pede confirmação
        from okami import menu
        if not menu.confirm(f"Instalar skill de fonte '{src_info.trust}' (scan {verdict})?", default=False):
            console.print(f"[dim]cancelado. Quarentena: {quarantine}[/dim]")
            console.print("[dim]marque a origem como confiável: okami skill tap github <org>[/dim]")
            raise typer.Exit(0)

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


