"""Perfis de AUTH (metadata, sem segredo): `okami auth` lista; `auth status --json`."""
from __future__ import annotations

import typer

from okami.cli._app import app, console
from okami.cli._shared import _load

auth_app = typer.Typer(invoke_without_command=True,
                       help="Perfis de AUTH (metadata, sem segredo): `okami auth` lista; `auth status --json`.")
app.add_typer(auth_app, name="auth")


@auth_app.callback(invoke_without_command=True)
def auth_main(ctx: typer.Context) -> None:
    """`okami auth` sem subcomando = lista os perfis de autenticação (tipo, status, onde mora)."""
    if ctx.invoked_subcommand is not None:
        return
    auth_list()


@auth_app.command("list")
def auth_list() -> None:
    """Lista os perfis de auth — tipo (oauth/cli/api_key), status, e ONDE mora a credencial (sem o valor)."""
    from rich.text import Text

    from okami.cli import _ui
    from okami.core.auth_profiles import build_auth_profiles
    profs = build_auth_profiles(_load())
    console.print()
    console.print(_ui.header("auth", "perfis de credencial · sem expor o valor"))
    console.print()
    t = _ui.data_table(
        ("", {"width": 2, "no_wrap": True}),
        ("provider", {"style": f"bold {_ui.FG}", "no_wrap": True}),
        ("tipo", {"style": _ui.MUTE, "no_wrap": True}),
        ("sub", {"justify": "center", "no_wrap": True}),
        ("status", {"no_wrap": True}),
        ("credencial (onde)", {"style": _ui.SOFT, "overflow": "ellipsis", "no_wrap": True}),
    )
    for p in profs:
        mark = Text("★", style=_ui.ORANGE) if p["default"] else Text(" ")
        sub = Text("✓", style=f"bold {_ui.GREEN}") if p["subscription"] else Text("—", style=_ui.MUTE)
        t.add_row(mark, p["name"], p["kind"], sub, _ui.badge(p["status"]), p["location"])
    console.print(t)
    console.print(_ui.hint("★ default · sub ✓ = assinatura OAuth/CLI (nunca pay-as-you-go) · okami login <provider>"))
    console.print()


@auth_app.command("status")
def auth_status(json_out: bool = typer.Option(False, "--json", help="Saída JSON (monitoramento/CI).")) -> None:
    """Status dos perfis de auth (machine-readable com --json)."""
    from okami.core.auth_profiles import build_auth_profiles
    profs = build_auth_profiles(_load())
    if json_out:
        import json as _json
        console.print_json(_json.dumps({"profiles": profs}, ensure_ascii=False))
        raise typer.Exit(0 if all(p["status"] != "missing" or not p["default"] for p in profs) else 1)
    from rich.text import Text

    from okami.cli import _ui
    for p in profs:
        line = Text("  ")
        line.append_text(_ui.badge(p["status"]))
        line.append(f"  {p['name']}", style=f"bold {_ui.FG}")
        line.append(f"   {p['kind']} · {p['location']}", style=_ui.MUTE)
        console.print(line)
