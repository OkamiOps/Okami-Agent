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


def _write_local(tmp_path, body: str):
    # `config get` lê a config efetiva (okami.yaml base + overrides) → precisa do base existir.
    (tmp_path / "okami.yaml").write_text(body, encoding="utf-8")


def test_config_get_redacts_sensitive_scalar(tmp_path, monkeypatch):
    """#9: `config get` de chave sensível NÃO cospe o valor cru (antes imprimia o token)."""
    monkeypatch.chdir(tmp_path)
    _write_local(tmp_path, "channels:\n  telegram:\n    token: 12345:supersecretvalue\n")
    res = runner.invoke(app, ["config", "get", "channels.telegram.token"])
    assert res.exit_code == 0
    assert "supersecretvalue" not in res.output and "***" in res.output


def test_config_get_raw_flag_reveals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_local(tmp_path, "channels:\n  telegram:\n    token: 12345:supersecretvalue\n")
    res = runner.invoke(app, ["config", "get", "channels.telegram.token", "--raw"])
    assert res.exit_code == 0 and "supersecretvalue" in res.output


def test_config_get_secret_valued_innocuous_key(tmp_path, monkeypatch):
    """Mesmo com chave inócua, valor que PARECE segredo (sk-…) é mascarado."""
    monkeypatch.chdir(tmp_path)
    _write_local(tmp_path, "note: sk-abcdefghijklmnop0123456789\n")  # pragma: allowlist secret
    res = runner.invoke(app, ["config", "get", "note"])
    assert res.exit_code == 0 and "sk-abcdefghijklmnop0123456789" not in res.output  # pragma: allowlist secret


def test_config_get_normal_scalar_shown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_local(tmp_path, "memory:\n  backend: holographic\n")
    res = runner.invoke(app, ["config", "get", "memory.backend"])
    assert res.exit_code == 0 and "holographic" in res.output
