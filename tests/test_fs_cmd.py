"""Comando `okami fs` — liberar acesso a arquivos numa linha (sem editar YAML na mão).

  okami fs home              → agente alcança tudo embaixo de ~/ (Documents, Pictures, Desktop…)
  okami fs full              → filesystem inteiro
  okami fs workspace         → volta ao jail (default seguro)
  okami fs home --allow /Volumes/x   → home + extra
"""

from __future__ import annotations

import yaml
from typer.testing import CliRunner

from okami.cli import app

runner = CliRunner()


def _spec(tmp_path, aid="okami"):
    return yaml.safe_load((tmp_path / aid / "agent.yaml").read_text())


def test_fs_home_writes_profile(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    res = runner.invoke(app, ["fs", "home"])
    assert res.exit_code == 0, res.output
    assert _spec(tmp_path)["tools"]["fs"] == "home"


def test_fs_full(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    runner.invoke(app, ["fs", "full"])
    assert _spec(tmp_path)["tools"]["fs"] == "full"


def test_fs_workspace_resets(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    runner.invoke(app, ["fs", "home"])
    runner.invoke(app, ["fs", "workspace"])
    assert _spec(tmp_path)["tools"]["fs"] == "workspace"


def test_fs_with_allow_extra(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    runner.invoke(app, ["fs", "home", "--allow", "/Volumes/x, /data"])
    spec = _spec(tmp_path)
    assert spec["tools"]["fs"] == "home"
    assert spec["tools"]["allow_paths"] == ["/Volumes/x", "/data"]


def test_fs_invalid_mode_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    res = runner.invoke(app, ["fs", "banana"])
    assert res.exit_code != 0
    low = res.output.lower()
    assert "workspace" in low and "home" in low and "full" in low   # mostra os modos válidos


def test_fs_shows_in_help():
    out = runner.invoke(app, ["help"]).output.lower()
    assert "fs home" in out or "okami fs" in out
