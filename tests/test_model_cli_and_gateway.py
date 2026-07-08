"""`okami model` (CLI) e `/model` (gateway) — mesma resolução via okami/llm/model_aliases.py,
persistência em okami.local.yaml (--save) e /models numerado (mobile-friendly)."""

from __future__ import annotations

import json

import yaml
from okami.gateway.endpoint_commands import EndpointCommandsMixin


def _write_cfg(tmp_path):
    (tmp_path / "okami.yaml").write_text(
        "default_provider: claude\n"
        "providers:\n"
        "  claude:\n"
        "    model: claude-subscription/claude-opus-4-8\n"
        "    auth: oauth_subscription\n"
        "    transport: claude_cli\n"
        "    tier: strong\n"
        "    models: [claude-opus-4-8, claude-sonnet-4-6, claude-haiku-4-5-20251001]\n"
        "  codex:\n"
        "    model: openai-codex/gpt-5.5\n"
        "    auth: oauth_subscription\n"
        "    transport: codex_oauth\n"
        "    tier: strong\n"
        "    models: [gpt-5.5, gpt-5.4]\n",
        encoding="utf-8")


# --- okami model (CLI) --------------------------------------------------

def test_model_list_json(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.chdir(tmp_path)
    _write_cfg(tmp_path)
    res = CliRunner().invoke(app, ["model", "list", "--json"])
    assert res.exit_code == 0, res.output
    rows = json.loads(res.output)
    aliases = {r["alias"] for r in rows}
    assert {"sonnet", "opus", "codex", "smart"} <= aliases
    sonnet = next(r for r in rows if r["alias"] == "sonnet")
    assert sonnet["provider"] == "claude" and sonnet["model"] == "claude-sonnet-4-6"


def test_model_token_non_interactive_persists_and_reports(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.chdir(tmp_path)
    _write_cfg(tmp_path)
    res = CliRunner().invoke(app, ["model", "sonnet"])
    assert res.exit_code == 0, res.output
    assert "claude" in res.output and "claude-sonnet-4-6" in res.output
    local = yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))
    assert local["default_provider"] == "claude"
    assert local["providers"]["claude"]["model"] == "claude-subscription/claude-sonnet-4-6"


def test_model_unknown_alias_errors_clearly(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.chdir(tmp_path)
    _write_cfg(tmp_path)
    res = CliRunner().invoke(app, ["model", "clawd"])
    assert res.exit_code != 0
    assert "desconhecido" in res.output


def test_model_add_provider_still_registers(tmp_path, monkeypatch):
    # smoke: registrar okami.cli.commands.model no __init__ não quebra os outros comandos de provider.
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.chdir(tmp_path)
    _write_cfg(tmp_path)
    res = CliRunner().invoke(app, ["provider", "list"])
    assert res.exit_code == 0, res.output


# --- /model (gateway) ----------------------------------------------------

class _FakeSession:
    def __init__(self):
        self.model_override = ""
        self.provider_override = ""


class _FakeEndpoint(EndpointCommandsMixin):
    def __init__(self, cfg):
        self.cfg = cfg


def test_gateway_model_cmd_resolves_alias():
    from okami.config import build_config
    cfg = build_config({
        "default_provider": "claude",
        "providers": {
            "claude": {"model": "claude-subscription/claude-opus-4-8", "auth": "oauth_subscription",
                      "transport": "claude_cli", "tier": "strong",
                      "models": ["claude-opus-4-8", "claude-sonnet-4-6"]},
            "codex": {"model": "openai-codex/gpt-5.5", "auth": "oauth_subscription",
                     "transport": "codex_oauth", "tier": "strong", "models": ["gpt-5.5"]},
        },
    })
    ep = _FakeEndpoint(cfg)
    s = _FakeSession()
    out = ep._model_cmd(s, "sonnet")
    assert s.provider_override == "claude"
    assert s.model_override == "claude-sonnet-4-6"
    assert "claude" in out


def test_gateway_model_cmd_unknown_alias_returns_error_not_exception():
    from okami.config import build_config
    cfg = build_config({
        "default_provider": "claude",
        "providers": {"claude": {"model": "claude-subscription/claude-opus-4-8",
                                 "auth": "oauth_subscription", "transport": "claude_cli", "tier": "strong"}},
    })
    ep = _FakeEndpoint(cfg)
    out = ep._model_cmd(_FakeSession(), "clawd")
    assert out.startswith("❌")


def test_gateway_model_cmd_numeric_index_uses_models_listing_order():
    from okami.config import build_config
    cfg = build_config({
        "default_provider": "claude",
        "providers": {
            "claude": {"model": "claude-subscription/claude-opus-4-8", "auth": "oauth_subscription",
                      "transport": "claude_cli", "tier": "strong"},
            "codex": {"model": "openai-codex/gpt-5.5", "auth": "oauth_subscription",
                     "transport": "codex_oauth", "tier": "strong"},
        },
    })
    ep = _FakeEndpoint(cfg)
    ep._models_text()                          # popula self._models_index (ordem = cfg.providers)
    s = _FakeSession()
    ep._model_cmd(s, "2")
    assert s.provider_override == "codex"


def test_gateway_model_cmd_save_persists_local_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    _write_cfg(tmp_path)
    from okami.config import load_config
    cfg = load_config()
    ep = _FakeEndpoint(cfg)
    s = _FakeSession()
    out = ep._model_cmd(s, "sonnet --save")
    assert "💾" in out or "saved" in out.lower()
    local = yaml.safe_load((tmp_path / "okami.local.yaml").read_text(encoding="utf-8"))
    assert local["default_provider"] == "claude"
    assert local["providers"]["claude"]["model"] == "claude-subscription/claude-sonnet-4-6"
