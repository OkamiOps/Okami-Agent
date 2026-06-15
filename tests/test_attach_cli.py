"""Item 8 (#8): CLI `okami attach` — cliente WS p/ um gateway remoto (okami serve --ws)."""
from __future__ import annotations

from typer.testing import CliRunner

from okami.cli import app

runner = CliRunner()


def test_attach_unreachable_exits_nonzero():
    # Sem servidor no destino → conecta falha → erro limpo (exit != 0), não trava.
    res = runner.invoke(app, ["attach", "ws://127.0.0.1:1/attach", "--token", "x"])
    assert res.exit_code != 0


def test_attach_command_registered():
    res = runner.invoke(app, ["attach", "--help"])
    assert res.exit_code == 0 and "attach" in res.stdout.lower()
