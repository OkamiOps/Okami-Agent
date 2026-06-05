"""Sprint 1 — fail-closed ("não vaza, não abre, não quebra").

Trava por teste: harness nega ação sensível sem approver; Telegram deny-by-default;
.env escrito 0600; MCP/sanitização não vaza segredo.
"""

from __future__ import annotations

import json
import os

import pytest

from okami.core import Harness, Task


def J(tool: str, **args) -> str:
    return "```json\n" + json.dumps({"tool": tool, "args": args}) + "\n```"


class Script:
    def __init__(self, outputs, default="ok, deixa pra depois."):
        self.outputs, self.default = list(outputs), default

    def __call__(self, messages, schema=None):
        return self.outputs.pop(0) if self.outputs else self.default


# ---------------------------------------------------------------- harness fail-closed
def test_harness_denies_sensitive_without_approver(tmp_path):
    """Sem approver, escrever em SOUL.md (identity_file) é NEGADO — o arquivo não nasce."""
    h = Harness(Script([J("write_file", path="SOUL.md", content="x"),
                        J("respond", message="ok, desisto")]), Task(goal="muda a SOUL"), tmp_path)
    assert h.approve({"tool": "write_file"}) is False          # default = deny
    h.run()
    assert not (tmp_path / "SOUL.md").exists()                  # ação sensível bloqueada


def test_harness_allows_sensitive_with_explicit_approver(tmp_path):
    """Com approver explícito (yolo), a mesma ação passa — prova que o default é a trava, não um bug."""
    h = Harness(Script([J("write_file", path="SOUL.md", content="x"),
                        J("respond", message="feito")]), Task(goal="muda a SOUL"), tmp_path,
                approve=lambda req: True)
    h.run()
    assert (tmp_path / "SOUL.md").read_text() == "x"


# ---------------------------------------------------------------- telegram deny-by-default
def test_telegram_deny_by_default():
    from okami.channels.telegram import TelegramChannel
    ch = TelegramChannel("dummy-token")
    assert ch.allowed("123") is False                          # sem allowlist → NINGUÉM
    assert TelegramChannel("t", allow_all=True).allowed("123") is True       # só explícito abre
    only = TelegramChannel("t", allow_chats=["123"])
    assert only.allowed("123") is True and only.allowed("999") is False


# ---------------------------------------------------------------- .env 0600 + atômico
@pytest.mark.skipif(os.name == "nt", reason="permissões POSIX")
def test_set_env_var_writes_0600(tmp_path):
    from okami.cli import _set_env_var
    env = tmp_path / ".env"
    _set_env_var("MIMO_API_KEY", "sk-segredo", path=str(env))
    assert "MIMO_API_KEY=sk-segredo" in env.read_text()
    assert (env.stat().st_mode & 0o777) == 0o600              # só o dono lê/escreve
    _set_env_var("MIMO_API_KEY", "sk-novo", path=str(env))    # update mantém 0600
    assert "sk-novo" in env.read_text() and (env.stat().st_mode & 0o777) == 0o600


# ---------------------------------------------------------------- MCP não vaza ambiente
def test_mcp_uses_sanitized_env(monkeypatch):
    """McpStdioClient.start() monta o env via sanitized_env() → segredo do ambiente NÃO vai pro servidor."""
    monkeypatch.setenv("SECRET_TOKEN", "leak-me")
    captured = {}

    class FakePopen:
        def __init__(self, *a, env=None, **k):
            captured["env"] = env

        def __getattr__(self, _):                              # stdin/stdout/etc. nem usados aqui
            return lambda *a, **k: None

    from okami.integrations import mcp
    monkeypatch.setattr(mcp.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(mcp.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda s: None})())
    cli = mcp.McpStdioClient("echo", env={"ALLOWED": "1"})
    try:
        cli.start()
    except Exception:  # noqa: BLE001 — só nos importa o env capturado
        pass
    assert captured["env"].get("ALLOWED") == "1"               # env extra explícito (allowlist) passa
    assert "SECRET_TOKEN" not in captured["env"]               # segredo do ambiente NÃO vaza


# ---------------------------------------------------------------- segredo GLOBAL (~/.okami/.env)
def test_secret_config_set_writes_global(tmp_path, monkeypatch):
    """`okami config set <SEGREDO>` grava no .env GLOBAL (~/.okami/.env), 0600 — vale em qualquer workspace."""
    monkeypatch.setenv("HOME", str(tmp_path))                  # ~ → tmp
    from okami.config import global_env_path
    from okami.cli import _set_env_var
    _set_env_var("ELEVENLABS_API_KEY", "sk-eleven")            # path=None → global
    g = global_env_path()
    assert g == tmp_path / ".okami" / ".env"
    assert "ELEVENLABS_API_KEY=sk-eleven" in g.read_text()
    if os.name != "nt":
        assert (g.stat().st_mode & 0o777) == 0o600
