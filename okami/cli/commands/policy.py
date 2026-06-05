"""Conformance de POLÍTICA autorada (#P1.3): `okami policy check/init/show`."""
from __future__ import annotations

from pathlib import Path

import typer

from okami.cli._app import app, console
from okami.cli._shared import _collect_channels, _load

policy_app = typer.Typer(help="Conformance de POLÍTICA autorada (#P1.3): `okami policy check/init/show`.")
app.add_typer(policy_app, name="policy")


@policy_app.command("check")
def policy_check(
    json_out: bool = typer.Option(False, "--json", help="Artefato de conformance JSON (CI/pre-deploy)."),
    policy_file: str = typer.Option(None, "--policy", help="Caminho do okami.policy.yaml (default: auto-descobre)."),
    strict: bool = typer.Option(False, "--strict", help="Postura de PRODUÇÃO/GA (ambiente hostil/público)."),
) -> None:
    """Avalia config+workspace contra a policy AUTORADA. `--strict` = posture de produção. Exit≠0 se falha."""
    from pathlib import Path as _P

    from okami.core.lint import summarize
    from okami.core.policy import conformance_artifact, evaluate, load_policy, strict_policy
    policy, source = load_policy(_P(policy_file) if policy_file else None)
    if strict:
        policy, source = strict_policy(policy), f"{source} + produção (--strict)"
    raw, channels = _collect_channels()
    findings = evaluate(_load(), policy, raw=raw, channels=channels)
    s = summarize(findings)
    if json_out:
        import json as _json
        console.print_json(_json.dumps(conformance_artifact(findings, policy_source=source), ensure_ascii=False))
        raise typer.Exit(0 if s["ok"] else 1)
    from rich.text import Text

    from okami.cli import _ui
    console.print()
    console.print(_ui.header("policy check", source + (" · produção" if strict else "")))
    console.print()
    shown = [x for x in findings if x.level != "pass"]
    if not shown:
        console.print(_ui.badge("pass", "nenhum desvio — tudo conforme"))
    for x in shown:
        line = Text("  ")
        line.append_text(_ui.dot(x.level))
        line.append(f"  {x.check}", style=f"bold {_ui.FG}")
        line.append(f"   {x.message}", style=_ui.SOFT)
        console.print(line)
        if x.fix:
            console.print(Text("       ").append_text(_ui.hint(x.fix)))
    console.print()
    c = s["counts"]
    verdict = Text("  ")
    verdict.append_text(_ui.badge("ok", "conforme") if s["ok"] else _ui.badge("fail", f"{c['fail']} falha(s)"))
    verdict.append(f"    {c['pass']} ok · {c['warn']} avisos · {c['fail']} falhas", style=_ui.MUTE)
    console.print(verdict)
    console.print()
    raise typer.Exit(0 if s["ok"] else 1)


@policy_app.command("init")
def policy_init(
    force: bool = typer.Option(False, "--force", help="Sobrescreve um okami.policy.yaml existente."),
) -> None:
    """Cria um okami.policy.yaml inicial (baseline comentada) p/ você autorar a conformance."""
    from okami.core.policy import scaffold
    p = Path("okami.policy.yaml")
    if p.exists() and not force:
        console.print("[yellow]okami.policy.yaml já existe[/yellow] — use --force p/ sobrescrever.")
        raise typer.Exit(1)
    p.write_text(scaffold(), encoding="utf-8")
    console.print("[green]✓ okami.policy.yaml criado[/green] [dim](edite e rode: okami policy check)[/dim]")


@policy_app.command("show")
def policy_show(
    strict: bool = typer.Option(False, "--strict", help="Mostra a postura de PRODUÇÃO/GA (overlay aplicado)."),
) -> None:
    """Mostra a policy EFETIVA (baseline + okami.policy.yaml autorado; --strict aplica a postura de produção)."""
    import yaml as _yaml

    from okami.core.policy import load_policy, strict_policy
    policy, source = load_policy()
    if strict:
        policy, source = strict_policy(policy), f"{source} + produção"
    if not console.is_terminal:                       # pipe → YAML cru (com a fonte como comentário)
        console.print(f"# policy: {source}")
        console.print(_yaml.safe_dump(policy, allow_unicode=True, sort_keys=False))
        return
    from rich.syntax import Syntax

    from okami.cli import _ui
    console.print()
    console.print(_ui.header("policy", "política de conformance efetiva"))
    console.print()
    body = Syntax(_yaml.safe_dump(policy, allow_unicode=True, sort_keys=False), "yaml",
                  theme="ansi_dark", background_color="default")
    console.print(_ui.card(body, title="policy", subtitle=source))
