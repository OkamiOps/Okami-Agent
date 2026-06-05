"""Processo INTERATIVO com PTY (#1/#8): start interactive + process_write injeta no stdin."""

from __future__ import annotations

import sys
import time

import pytest

from okami.core.processes import ProcessManager
from okami.core.sandbox import SandboxPolicy
from okami.core.tools import ProcessStart, ProcessWrite, ToolContext


def _wait_log(pm, pid, needle, tries=40):
    for _ in range(tries):
        if needle in pm.log(pid):
            return True
        time.sleep(0.1)
    return False


@pytest.mark.skipif(sys.platform == "win32", reason="PTY é POSIX")
def test_interactive_cat_roundtrip(tmp_path):
    pm = ProcessManager(tmp_path)
    meta = pm.start("cat", interactive=True)
    assert meta["interactive"] and pm.poll(meta["id"])["status"] == "running"
    time.sleep(0.3)
    assert pm.write(meta["id"], "ping-echo")        # manda input + Enter
    assert _wait_log(pm, meta["id"], "ping-echo")    # cat (e o echo do PTY) devolvem
    pm.kill(meta["id"])
    assert not pm._ctrlf(meta["id"]).exists()        # FIFO removido no kill


@pytest.mark.skipif(sys.platform == "win32", reason="PTY é POSIX")
def test_interactive_python_repl(tmp_path):
    pm = ProcessManager(tmp_path)
    meta = pm.start("python3 -i -q", interactive=True)
    time.sleep(0.4)
    pm.write(meta["id"], "print(6*7)")
    assert _wait_log(pm, meta["id"], "42")
    pm.write(meta["id"], "exit()")
    time.sleep(0.4)
    st = pm.poll(meta["id"])
    assert st["status"] == "exited"


@pytest.mark.skipif(sys.platform == "win32", reason="PTY é POSIX")
def test_write_to_noninteractive_fails(tmp_path):
    pm = ProcessManager(tmp_path)
    meta = pm.start("echo nope")
    pm.wait(meta["id"], timeout=10)
    assert pm.write(meta["id"], "x") is False        # não-interativo → não aceita input


def test_interactive_blocked_under_docker(tmp_path, monkeypatch):
    from okami.core import sandbox
    monkeypatch.setattr(sandbox.shutil, "which", lambda *_: "/usr/bin/docker")  # finge docker presente
    pm = ProcessManager(tmp_path)
    with pytest.raises(ValueError, match="interativo"):
        pm.start("cat", SandboxPolicy(backend="docker"), interactive=True)


@pytest.mark.skipif(sys.platform == "win32", reason="PTY é POSIX")
def test_process_write_tool(tmp_path):
    ctx = ToolContext(workspace=tmp_path, sandbox=SandboxPolicy())
    started = ProcessStart().run({"cmd": "cat", "interactive": True}, ctx)
    assert started.ok and "interativo" in started.output
    pid = started.output.split("processo ")[1].split(" ")[0]
    time.sleep(0.3)
    out = ProcessWrite().run({"id": pid, "data": "hello-tool"}, ctx)
    assert out.ok
    pm = ProcessManager(tmp_path)
    assert _wait_log(pm, pid, "hello-tool")
    pm.kill(pid)


def test_process_write_registered():
    from okami.core.tool_registry import missing
    from okami.core.tools import default_registry
    reg = default_registry()
    assert "process_write" in reg and missing(reg.keys()) == []
