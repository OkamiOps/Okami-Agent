"""Comando `okami channel` — jeito FÁCIL de conectar o Telegram (a dor: hoje só via `okami setup`).

  okami channel add telegram <token> [--allow 123,456 | --allow-all] [--agent okami]
  okami channel list
  okami channel remove telegram [--agent okami]"""

from __future__ import annotations

import yaml
from typer.testing import CliRunner

from okami.cli import app

runner = CliRunner()


def _agent_yaml(tmp_path, aid="okami"):
    return yaml.safe_load((tmp_path / aid / "agent.yaml").read_text())


def test_channel_add_telegram_writes_token(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    res = runner.invoke(app, ["channel", "add", "telegram", "12345:ABCDEF", "--allow", "777"])
    assert res.exit_code == 0, res.output
    spec = _agent_yaml(tmp_path)
    assert spec["channels"]["telegram"]["token"] == "12345:ABCDEF"
    assert spec["channels"]["telegram"]["allow_chats"] == [777]


def test_channel_add_allow_all(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    res = runner.invoke(app, ["channel", "add", "telegram", "tok", "--allow-all"])
    assert res.exit_code == 0
    spec = _agent_yaml(tmp_path)
    assert spec["channels"]["telegram"]["allow_all"] is True


def test_channel_add_requires_token(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    res = runner.invoke(app, ["channel", "add", "telegram"])
    assert res.exit_code != 0


def test_channel_add_warns_when_no_allowlist(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    res = runner.invoke(app, ["channel", "add", "telegram", "tok"])   # sem allow nem allow-all
    assert res.exit_code == 0
    # avisa que o bot fica MUDO até liberar alguém (deny-by-default) — orienta o pareamento
    low = res.output.lower()
    assert "allow" in low or "pair" in low or "ninguém" in low or "mudo" in low


def test_channel_list_shows_configured(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    runner.invoke(app, ["channel", "add", "telegram", "tok", "--allow-all"])
    res = runner.invoke(app, ["channel", "list"])
    assert res.exit_code == 0 and "telegram" in res.output.lower()


def test_channel_remove(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    runner.invoke(app, ["channel", "add", "telegram", "tok", "--allow-all"])
    res = runner.invoke(app, ["channel", "remove", "telegram"])
    assert res.exit_code == 0
    spec = _agent_yaml(tmp_path)
    assert "telegram" not in (spec.get("channels") or {})


def test_channel_unknown_type_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    res = runner.invoke(app, ["channel", "add", "fax", "tok"])
    assert res.exit_code != 0 and "telegram" in res.output.lower()    # diz os tipos válidos
