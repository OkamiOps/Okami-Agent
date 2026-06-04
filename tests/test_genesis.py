"""Gênese / onboarding de primeiro contato (§8.2): detecção + finish_setup."""

from __future__ import annotations

from okami.core.tools import FinishSetup, ToolContext
from okami.gateway import genesis_pending


def test_genesis_pending_lifecycle(tmp_path):
    assert genesis_pending(tmp_path) is True                  # agente novo: sem USER.md, sem marca
    (tmp_path / "USER.md").write_text("# USER\n", encoding="utf-8")   # já conhece a pessoa
    assert genesis_pending(tmp_path) is False                 # → não re-onboarda
    assert (tmp_path / ".okami" / "genesis.done").exists()    # e sela de uma vez


def test_finish_setup_writes_marker_and_user(tmp_path):
    res = FinishSetup().run({"about_user": "Marcos, dev do Okami"}, ToolContext(workspace=tmp_path))
    assert res.ok and res.effect
    assert (tmp_path / ".okami" / "genesis.done").exists()
    assert "Marcos" in (tmp_path / "USER.md").read_text(encoding="utf-8")
    assert genesis_pending(tmp_path) is False                 # selado → fim do onboarding


def test_finish_setup_without_about_user_seals_but_no_user_md(tmp_path):
    res = FinishSetup().run({}, ToolContext(workspace=tmp_path))   # "deixa pra depois"
    assert res.ok
    assert (tmp_path / ".okami" / "genesis.done").exists()
    assert not (tmp_path / "USER.md").exists()
