"""Item 2 (#8): superfície CLI consent-first — `okami suggestions` list · accept · dismiss."""
from __future__ import annotations

from typer.testing import CliRunner

from okami.automation.suggestions import SuggestionStore
from okami.cli import app

runner = CliRunner()


def test_cli_list_shows_pending(tmp_path):
    SuggestionStore(tmp_path).add(text="resumo diário?", schedule="0 8 * * *", prompt="faça o resumo", dedup_key="d")
    res = runner.invoke(app, ["suggestions", "list", "--workspace", str(tmp_path)])
    assert res.exit_code == 0 and "resumo diário?" in res.stdout


def test_cli_accept_creates_job(tmp_path):
    sid = SuggestionStore(tmp_path).add(text="r", schedule="0 8 * * *", prompt="faça o resumo", dedup_key="d")
    res = runner.invoke(app, ["suggestions", "accept", sid, "--workspace", str(tmp_path)])
    assert res.exit_code == 0
    from okami.automation.scheduler import Scheduler
    assert any("resumo" in j["prompt"] for j in Scheduler(str(tmp_path)).load())
    assert SuggestionStore(tmp_path).pending() == []


def test_cli_dismiss_latches(tmp_path):
    s = SuggestionStore(tmp_path)
    sid = s.add(text="x", schedule="0 8 * * *", prompt="p", dedup_key="k")
    res = runner.invoke(app, ["suggestions", "dismiss", sid, "--workspace", str(tmp_path)])
    assert res.exit_code == 0 and s.pending() == []
