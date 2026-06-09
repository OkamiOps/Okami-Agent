"""Release-readiness / strict-freshness (#P2): `okami readiness`.

Responde, na linguagem do operador, três perguntas de GA:
  • strict green   — a postura VERSIONADA passa `--strict`? (offline, autoritativo)
  • CI green       — o ci.yml passou no commit ATUAL?
  • strict HEAD ✓  — a conformance estrita foi rodada no HEAD ATUAL? (senão STALE)

`--refresh` dispara o gate estrito em modo bloqueante (enforce=true) p/ recuperar a frescura.
"""
from __future__ import annotations

import typer
from okami.i18n import t as _tr

from okami.cli._app import app, console


@app.command("readiness", help=_tr("cli.readiness", _default="Release readiness: strict green · CI green · strict HEAD match. Exit≠0 if NOT ready."))
def readiness(
    json_out: bool = typer.Option(False, "--json", help=_tr("cli.readiness.json", _default="Machine-readable signals (CI / release bot).")),
    no_gh: bool = typer.Option(False, "--no-gh", help=_tr("cli.readiness.no_gh", _default="Local verdict only (offline; ignores GitHub Actions).")),
    refresh: bool = typer.Option(False, "--refresh", help=_tr("cli.readiness.refresh", _default="Trigger the strict gate (enforce=true) on HEAD and exit.")),
    branch: str = typer.Option("main", "--branch", help=_tr("cli.readiness.branch", _default="Branch to query CI / trigger the gate.")),
) -> None:
    """Prontidão de release: strict green · CI green · strict HEAD match. Exit≠0 se NÃO pronto."""
    from okami.core import readiness as R

    if refresh:
        ok, msg = R.trigger_strict_enforce(branch)
        console.print(("[green]✓[/green] " if ok else "[red]✗[/red] ") + msg)
        raise typer.Exit(0 if ok else 1)

    rep = R.collect(use_gh=not no_gh)
    data = rep.as_dict()

    if json_out:
        import json as _json
        console.print_json(_json.dumps(data, ensure_ascii=False))
        raise typer.Exit(0 if rep.verdict == "ready" else 1)

    from rich.text import Text

    from okami.cli import _ui

    def tri(v: bool | None) -> Text:
        if v is None:
            return _ui.badge("dim", "?")
        return _ui.badge("yes", "sim") if v else _ui.badge("fail", "não")

    head7 = (rep.head or "—")[:7]
    console.print()
    console.print(_ui.header("readiness", f"prontidão de release · HEAD {head7}"))
    console.print()

    rows = [
        ("CI green", _wf_line(rep.ci, rep.ci_green, rep.ci_head_match, head7)),
        ("strict green", tri(rep.local_strict_ok).append(
            f"   postura versionada ({rep.local_source})", style=_ui.MUTE)),
        ("strict HEAD match", _head_match_line(rep.strict, rep.strict_head_match)),
    ]
    console.print(_ui.card(_ui.kv_grid(rows, gutter=3), title="sinais", accent=_ui.CYAN))
    console.print()

    verdict = rep.verdict
    badge_state = {"ready": "ok", "stale": "warn", "not_ready": "fail", "unknown": "dim"}[verdict]
    label = {"ready": "PRONTO p/ release", "stale": "STALE — strict verde, mas o HEAD andou",
             "not_ready": "NÃO pronto", "unknown": "indeterminado (sem dados de CI)"}[verdict]
    line = Text("  ")
    line.append_text(_ui.badge(badge_state, label))
    console.print(line)

    hint = {
        "stale": "okami readiness --refresh   (re-roda o gate estrito no HEAD atual)",
        "not_ready": "okami policy check --strict   (veja o desvio) · ajuste okami.yaml/okami.policy.yaml",
        "unknown": "instale/login o gh (GitHub CLI) p/ confirmar CI, ou rode com --no-gh p/ só o local",
    }.get(verdict)
    if hint:
        console.print(Text("  ").append_text(_ui.hint(hint)))
    console.print()
    raise typer.Exit(0 if verdict == "ready" else 1)


def _head_match_line(run, head_match):
    """Linha do 'strict HEAD match': a conformance estrita rodou no HEAD ATUAL? (senão STALE)."""
    from okami.cli import _ui
    if run is None:
        return _ui.badge("dim", "?").append("   sem dados (gh ausente/offline ou --no-gh)", style=_ui.MUTE)
    sha = (run.head_sha or "—")[:7]
    if head_match:
        return _ui.badge("yes", "sim").append(f"   strict rodou no HEAD ({sha})", style=_ui.MUTE)
    return _ui.badge("warn", "não").append(f"   último strict @ {sha} — o HEAD andou desde então", style=_ui.AMBER)


def _wf_line(run, green, head_match, head7):
    from okami.cli import _ui
    if run is None:
        return _ui.badge("dim", "?").append("   sem dados (gh ausente/offline ou --no-gh)", style=_ui.MUTE)
    if green is None:
        t = _ui.badge("dim", "em andamento")
    else:
        t = _ui.badge("yes", "sim") if green else _ui.badge("fail", "não")
    sha = (run.head_sha or "—")[:7]
    match = "HEAD ✓" if head_match else (f"@ {sha} (HEAD andou)" if head_match is False else f"@ {sha}")
    t.append(f"   {match}", style=(_ui.MUTE if head_match else _ui.AMBER))
    return t
