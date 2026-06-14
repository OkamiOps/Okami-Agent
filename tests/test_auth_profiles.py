"""Perfis de auth com metadata (#12): tipo/status/local — e NUNCA o segredo."""

from __future__ import annotations

import json
from types import SimpleNamespace

from okami.core.auth_profiles import build_auth_profiles


def _pc(**over):
    base = dict(transport="litellm", auth="api_key", tier="strong", model="m",
                api_key_env=None, api_key=None, ready=False)
    base.update(over)
    return SimpleNamespace(**base)


def _cfg(providers, default="codex"):
    return SimpleNamespace(providers=providers, default_provider=default)


def test_codex_is_oauth_subscription(monkeypatch, tmp_path):
    # isolamento: _oauth_expiry lê ~/.codex/auth.json e credentials reais — sem isto o teste depende
    # do estado de credencial do dev (token expirado → status 'expired', falso-negativo). HOME+OKAMI_HOME
    # p/ tmp → sem arquivo de auth → expiry None → status 'ready' (a config sintética tem ready=True).
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    cfg = _cfg({"codex": _pc(transport="codex_oauth", ready=True)})
    p = build_auth_profiles(cfg)[0]
    assert p["kind"] == "oauth" and p["subscription"] is True and p["default"] is True
    assert p["status"] == "ready"


def test_claude_cli_subscription():
    p = build_auth_profiles(_cfg({"claude": _pc(transport="claude_cli", ready=True)}, default="claude"))[0]
    assert p["kind"] == "cli" and p["subscription"] is True and "claude" in p["location"].lower()


def test_api_key_provider_shows_env_name_not_value(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "super-secret-value-123")
    cfg = _cfg({"mimo": _pc(transport="litellm", api_key_env="MIMO_API_KEY", ready=True)}, default="mimo")
    p = build_auth_profiles(cfg)[0]
    assert p["kind"] == "api_key" and p["subscription"] is False
    assert p["location"] == "env:MIMO_API_KEY"           # NOME da var, não o valor


def test_no_secret_value_leaks_anywhere(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-LEAKED-DO-NOT-SHOW")
    cfg = _cfg({"openai": _pc(api_key_env="OPENAI_API_KEY", api_key="literal-secret-xyz", ready=True)},
               default="openai")
    profs = build_auth_profiles(cfg)
    blob = json.dumps(profs)
    assert "sk-LEAKED-DO-NOT-SHOW" not in blob and "literal-secret-xyz" not in blob


def test_missing_status():
    p = build_auth_profiles(_cfg({"codex": _pc(transport="codex_oauth", ready=False)}))[0]
    assert p["status"] == "missing"


def test_expired_when_token_stale(tmp_path, monkeypatch):
    # auth.json com expiry no passado → status expired (lê SÓ o número, nunca o token)
    home = tmp_path
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    cdir = home / ".codex"
    cdir.mkdir()
    (cdir / "auth.json").write_text(json.dumps({"tokens": {"access_token": "SECRET", "expires_at": 100.0}}),
                                    encoding="utf-8")
    p = build_auth_profiles(_cfg({"codex": _pc(transport="codex_oauth", ready=True)}), now=1_000_000.0)[0]
    assert p["status"] == "expired" and p["expires_at"] == 100.0


def test_cli_auth_list(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: p\nproviders:\n  p:\n    tier: free\n    model: m\n    api_key_env: P_KEY\n",
        encoding="utf-8")
    res = CliRunner().invoke(app, ["auth", "status", "--json"])
    assert '"name": "p"' in res.output and "P_KEY" in res.output and "secret" not in res.output.lower()
