"""#17 Wave 4: comandos de terminal faltantes (dashboard) + descoberta no help."""
from __future__ import annotations

from typer.testing import CliRunner

from okami.cli import app

runner = CliRunner()


def test_dashboard_command_registered():
    res = runner.invoke(app, ["dashboard", "--help"])
    assert res.exit_code == 0 and "dashboard" in res.stdout.lower()


def test_dashboard_delegates_to_gui(monkeypatch):
    from okami.cli.commands import basics
    called = {}
    monkeypatch.setattr(basics, "gui", lambda **kw: called.update(kw))
    res = runner.invoke(app, ["dashboard", "--port", "9991", "--no-open"])
    assert res.exit_code == 0
    assert called.get("port") == 9991 and called.get("no_open") is True


def test_new_commands_discoverable_in_help():
    res = runner.invoke(app, ["help"])
    assert res.exit_code == 0
    low = res.stdout.lower()
    for cmd in ("moa", "lsp", "cost", "sessions", "dashboard", "gemini"):
        assert cmd in low, f"'{cmd}' não aparece em `okami help`"
