"""Process manager rumo a Hermes (#P1.4): fila de notificações, watch strikes, signal, reconcile."""

from __future__ import annotations

import time

import pytest

from okami.core.processes import ProcessManager


def _wait_exit(pm, pid, tries=50):
    for _ in range(tries):
        if pm.poll(pid).get("status") == "exited":
            return True
        time.sleep(0.1)
    return False


def test_drain_notifications_unifies_complete_and_watch(tmp_path):
    pm = ProcessManager(tmp_path)
    pm.start("echo Listening on 8080", notify=True, watch=["Listening on"])
    pid = pm.list()[0]["id"]
    _wait_exit(pm, pid)
    time.sleep(0.2)
    notes = pm.drain_notifications()
    kinds = {n["kind"] for n in notes}
    assert "complete" in kinds and "watch" in kinds
    assert pm.drain_notifications() == []                 # cada uma entregue só 1x (rate-limit)


def test_watch_strikes_threshold(tmp_path):
    pm = ProcessManager(tmp_path)
    # padrão só dispara com 3 ocorrências (strikes)
    pm.start("printf 'ERRO\\nERRO\\nok\\n'", watch=[{"pattern": "ERRO", "strikes": 3}])
    pid = pm.list()[0]["id"]
    _wait_exit(pm, pid)
    time.sleep(0.2)
    assert pm.drain_watch() == []                          # só 2 ERRO < 3 strikes → não dispara


def test_watch_strikes_fires_when_met(tmp_path):
    pm = ProcessManager(tmp_path)
    pm.start("printf 'ERRO\\nERRO\\nERRO\\n'", watch=[{"pattern": "ERRO", "strikes": 3}])
    pid = pm.list()[0]["id"]
    _wait_exit(pm, pid)
    time.sleep(0.2)
    hits = pm.drain_watch()
    assert len(hits) == 1 and hits[0]["count"] >= 3 and hits[0]["strikes"] == 3


@pytest.mark.skipif(not hasattr(__import__("signal"), "SIGUSR1"), reason="POSIX")
def test_signal_sends(tmp_path):
    pm = ProcessManager(tmp_path)
    pid = pm.start("sleep 30")["id"]
    assert pm.poll(pid)["status"] == "running"
    assert pm.signal(pid, "TERM") is True
    for _ in range(50):
        if pm.poll(pid)["status"] != "running":
            break
        time.sleep(0.1)
    assert pm.poll(pid)["status"] != "running"


def test_signal_invalid_name(tmp_path):
    pm = ProcessManager(tmp_path)
    pid = pm.start("sleep 5")["id"]
    assert pm.signal(pid, "NOPE") is False
    pm.kill(pid)


def test_signal_unknown_process(tmp_path):
    assert ProcessManager(tmp_path).signal("ghost", "TERM") is False


def test_reconcile_orphan(tmp_path):
    pm = ProcessManager(tmp_path)
    pid = pm.start("sleep 30")["id"]
    # simula crash do gateway: mata o processo por fora, SEM exitfile (estado fantasma 'running')
    import os
    import signal as _sig
    meta = pm._read_meta(pid)
    os.killpg(os.getpgid(meta["pid"]), _sig.SIGKILL)
    time.sleep(0.3)
    assert not pm._exitf(pid).exists()                    # ainda sem marcador
    fixed = pm.reconcile()
    assert fixed >= 1 and pm._exitf(pid).exists()
    assert pm.poll(pid)["status"] == "exited"             # estado virou durável


def test_process_signal_tool_registered():
    from okami.core.tool_registry import missing
    from okami.core.tools import default_registry
    reg = default_registry()
    assert "process_signal" in reg and missing(reg.keys()) == []


def test_process_signal_tool(tmp_path):
    from okami.core.sandbox import SandboxPolicy
    from okami.core.tools import ProcessStart, ProcessSignal, ToolContext
    ctx = ToolContext(workspace=tmp_path, sandbox=SandboxPolicy())
    started = ProcessStart().run({"cmd": "sleep 30"}, ctx)
    pid = started.output.split("processo ")[1].split(" ")[0]
    out = ProcessSignal().run({"id": pid, "signal": "TERM"}, ctx)
    assert out.ok and "TERM" in out.output
