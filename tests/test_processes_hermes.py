"""Process manager Hermes-grade (#1/#8): list, paginação, notify, watch, TTL, cap de log."""

from __future__ import annotations

from okami.core.processes import ProcessManager


def test_process_list_tool_registered():
    from okami.core.tools import default_registry
    reg = default_registry()
    assert "process_list" in reg
    from okami.core.tool_registry import missing
    assert missing(reg.keys()) == []                  # toda tool registrada tem metadata


def test_list_via_tool(tmp_path):
    from okami.core.tools import ProcessList, ToolContext
    pm = ProcessManager(tmp_path)
    pm.wait(pm.start("echo a")["id"], timeout=10)
    out = ProcessList().run({}, ToolContext(workspace=tmp_path))
    assert out.ok and "exited" in out.output


def test_log_pagination(tmp_path):
    pm = ProcessManager(tmp_path)
    pid = pm.start("printf 'l1\\nl2\\nl3\\nl4\\nl5\\n'")["id"]
    pm.wait(pid, timeout=10)
    page = pm.log_page(pid, offset=1, limit=2)
    assert page["total"] == 5 and page["shown"] == 2 and page["lines"] == ["l2", "l3"]
    last = pm.log_page(pid, offset=-2, limit=2)        # do fim
    assert last["lines"] == ["l4", "l5"]


def test_watch_patterns(tmp_path):
    pm = ProcessManager(tmp_path)
    pid = pm.start("echo 'Listening on 0.0.0.0:8080'", watch=["Listening on", "FATAL"])["id"]
    pm.wait(pid, timeout=10)
    hits = pm.watch_hits(pid)
    assert "Listening on" in hits and "FATAL" not in hits


def test_notify_on_complete_drain(tmp_path):
    pm = ProcessManager(tmp_path)
    pm.start("echo done", notify=True)
    pm.start("echo silent")                            # sem notify → não entra no drain
    pm.wait(pm.list()[0]["id"], timeout=10)
    import time
    time.sleep(0.3)
    done = pm.drain_completed()
    assert len(done) == 1 and done[0].get("notify") is True
    assert pm.drain_completed() == []                  # já avisado → não repete


def test_ttl_prune(tmp_path):
    pm = ProcessManager(tmp_path)
    pid = pm.start("echo x")["id"]
    pm.wait(pid, timeout=10)
    assert pm.prune(ttl_seconds=99999) == []           # recente → não poda
    removed = pm.prune(ttl_seconds=-1)                 # tudo é "velho" → poda
    assert pid in removed and not pm._meta(pid).exists()


def test_log_compaction_on_exit(tmp_path):
    pm = ProcessManager(tmp_path)
    pm._MAX_LOG = 2000
    pid = pm.start("python3 -c \"print('x'*50000)\"")["id"]
    pm.wait(pid, timeout=10)
    pm.poll(pid)                                       # dispara compactação pós-saída
    assert pm._logf(pid).stat().st_size <= pm._MAX_LOG + 200
    assert "compactado" in pm._logf(pid).read_text(encoding="utf-8")


def test_prune_processes_in_maintenance(tmp_path):
    from okami.core.maintenance import clean_workspace, prune_processes
    pm = ProcessManager(tmp_path)
    pm.wait(pm.start("echo x")["id"], timeout=10)
    assert prune_processes(tmp_path, ttl_hours=-1)      # poda imediata
    rep = clean_workspace(tmp_path)
    assert "processes_removed" in rep
