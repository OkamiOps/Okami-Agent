"""env_passthrough (fase 3) — opt-in p/ o sandbox local manter GH_TOKEN/SSH_AUTH_SOCK (senão são
removidos por sanitized_env), de modo que `git push`/`gh` LOCAL funcionem ao publicar código.
"""
from __future__ import annotations


def test_sanitized_env_strip_por_padrao(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "tok-FAKE-123")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
    from okami.core.tools.base import sanitized_env
    base = sanitized_env()
    assert "GH_TOKEN" not in base and "SSH_AUTH_SOCK" not in base   # default seguro: removidos


def test_sanitized_env_passthrough_mantem(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "tok-FAKE-123")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
    from okami.core.tools.base import sanitized_env
    keep = sanitized_env(passthrough=["GH_TOKEN", "SSH_AUTH_SOCK"])
    assert keep["GH_TOKEN"] == "tok-FAKE-123"                       # opt-in → passa
    assert keep["SSH_AUTH_SOCK"] == "/tmp/agent.sock"


def test_sandbox_policy_le_env_passthrough():
    from okami.core.sandbox import SandboxPolicy
    p = SandboxPolicy.from_config({"env_passthrough": ["GH_TOKEN", "SSH_AUTH_SOCK"]})
    assert list(p.env_passthrough) == ["GH_TOKEN", "SSH_AUTH_SOCK"]
    assert list(SandboxPolicy.from_config({}).env_passthrough) == []
