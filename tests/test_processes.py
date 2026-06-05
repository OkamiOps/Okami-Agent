"""Process runtime em background (#10): start/poll/wait/log/kill + bloqueio de caminho sensível."""

from __future__ import annotations

import time

import pytest

from okami.core.processes import ProcessManager


def test_start_poll_wait_log_roundtrip(tmp_path):
    pm = ProcessManager(tmp_path)
    meta = pm.start("echo ola-background")
    assert meta["id"] and meta["pid"]
    st = pm.wait(meta["id"], timeout=10)             # espera terminar
    assert st["status"] == "exited" and st["exit_code"] == 0
    assert "ola-background" in pm.log(meta["id"])     # log capturado


def test_nonzero_exit_code(tmp_path):
    pm = ProcessManager(tmp_path)
    st = pm.wait(pm.start("exit 3")["id"], timeout=10)
    assert st["status"] == "exited" and st["exit_code"] == 3


def test_kill_running_process(tmp_path):
    pm = ProcessManager(tmp_path)
    pid_id = pm.start("sleep 30")["id"]
    assert pm.poll(pid_id)["status"] == "running"
    assert pm.kill(pid_id) is True
    for _ in range(50):                               # dá um tempo p/ o SIGTERM derrubar
        if pm.poll(pid_id)["status"] != "running":
            break
        time.sleep(0.1)
    assert pm.poll(pid_id)["status"] != "running"


def test_start_blocks_sensitive_path(tmp_path):
    with pytest.raises(ValueError):
        ProcessManager(tmp_path).start("cat ~/.ssh/id_rsa")


def test_list_and_unknown(tmp_path):
    pm = ProcessManager(tmp_path)
    pm.wait(pm.start("echo x")["id"], timeout=10)
    assert any(p["status"] == "exited" for p in pm.list())
    assert pm.poll("naoexiste")["status"] == "unknown"


def test_process_start_blocked_by_approval_when_destructive(tmp_path):
    """process_start com comando destrutivo passa pela MESMA trava do run_shell (go/no-go)."""
    from okami.core import approval
    sens = approval.classify("process_start", {"cmd": "rm -rf /"})
    assert sens is not None and sens.risk == "critical"
