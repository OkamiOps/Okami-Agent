"""process_start usa a MESMA política do run_shell (#5): perfil, backend docker exigido, não-root."""

from __future__ import annotations

from pathlib import Path

import pytest

from okami.core import sandbox
from okami.core.processes import ProcessManager
from okami.core.sandbox import SandboxPolicy, docker_argv
from okami.core.tools import ProcessStart, RunShell, ToolContext


def test_profile_hardened_uses_auto_backend():
    p = SandboxPolicy.from_config({"profile": "hardened"})
    assert p.backend == "auto"
    # campo explícito vence o atalho
    assert SandboxPolicy.from_config({"profile": "hardened", "backend": "local"}).backend == "local"


def test_docker_argv_is_non_root_and_locked_down():
    argv = docker_argv("ls", Path("/tmp/ws"), SandboxPolicy(backend="docker"), name="okami-x")
    assert "--user" in argv and "--cap-drop" in argv
    assert argv[argv.index("--network") + 1] == "none"          # rede off por padrão
    assert argv[argv.index("--name") + 1] == "okami-x"          # nomeado p/ kill


def test_process_start_blocked_in_read_only(tmp_path):
    ctx = ToolContext(workspace=tmp_path, sandbox=SandboxPolicy(mode="read-only"))
    res = ProcessStart().run({"cmd": "sleep 1"}, ctx)
    assert not res.ok and "read-only" in res.output


def test_process_start_blocks_sensitive_path(tmp_path):
    ctx = ToolContext(workspace=tmp_path, sandbox=SandboxPolicy())
    res = ProcessStart().run({"cmd": "cat ~/.ssh/id_rsa"}, ctx)
    assert not res.ok and "sensível" in res.output


def test_process_start_docker_required_but_absent_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda *_: None)   # finge: sem docker
    pm = ProcessManager(tmp_path)
    with pytest.raises(ValueError, match="DESABILITADO"):
        pm.start("echo oi", SandboxPolicy(backend="docker"))


def test_process_start_local_still_works(tmp_path):
    """Backend local (default) segue funcionando — roundtrip real."""
    pm = ProcessManager(tmp_path)
    meta = pm.start("echo via-policy", SandboxPolicy(backend="local"))
    assert meta["backend"] == "local"
    st = pm.wait(meta["id"], timeout=10)
    assert st["status"] == "exited" and st["exit_code"] == 0 and "via-policy" in pm.log(meta["id"])


def test_run_shell_and_process_share_sensitive_guard(tmp_path):
    """run_shell e process_start aplicam o MESMO bloqueio de caminho sensível."""
    ctx = ToolContext(workspace=tmp_path, sandbox=SandboxPolicy())
    assert not RunShell().run({"cmd": "cat .env"}, ctx).ok
    assert not ProcessStart().run({"cmd": "cat .env"}, ctx).ok
