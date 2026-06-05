"""Segredo em chave pontilhada (#6): config NÃO grava segredo em texto no YAML versionável."""

from __future__ import annotations

from typer.testing import CliRunner

from okami.cli import app
from okami.cli.commands.config import _is_sensitive_dotted

runner = CliRunner()


def test_detects_sensitive_dotted_keys():
    assert _is_sensitive_dotted("providers.openai.api_key")
    assert _is_sensitive_dotted("channels.telegram.token")
    assert _is_sensitive_dotted("mcp.servers.x.headers.Authorization")
    assert _is_sensitive_dotted("memory.honcho.api_key")
    assert not _is_sensitive_dotted("memory.backend")
    assert not _is_sensitive_dotted("approvals.mode")


def test_config_set_refuses_plaintext_secret(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(app, ["config", "set", "channels.telegram.token", "12345:secrettoken"])
    assert res.exit_code == 2 and "segredo" in res.output.lower()
    local = tmp_path / "okami.local.yaml"
    assert not local.exists() or "secrettoken" not in local.read_text(encoding="utf-8")   # NÃO gravou


def test_config_set_allows_env_reference(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(app, ["config", "set", "channels.telegram.token", "${TELEGRAM_TOKEN}"])
    assert res.exit_code == 0
    assert "${TELEGRAM_TOKEN}" in (tmp_path / "okami.local.yaml").read_text(encoding="utf-8")   # ref ok


def test_config_set_normal_key_unaffected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(app, ["config", "set", "memory.backend", "holographic"])
    assert res.exit_code == 0 and "holographic" in (tmp_path / "okami.local.yaml").read_text(encoding="utf-8")
