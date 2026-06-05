"""Lock transacional de sessão (P0.5): appends concorrentes não duplicam; lock rouba dono morto."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from okami.gateway.sessions import TranscriptStore, _FileLock


def test_concurrent_appends_stay_unique(tmp_path):
    store = TranscriptStore(tmp_path)
    cid = "c1"

    def worker(i):
        store.append(cid, "user", f"msg {i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    nodes = store.read(cid)
    ids = [n["id"] for n in nodes]
    assert len(nodes) == 20 and len(set(ids)) == 20                  # 20 nós, ids únicos (sem corrida)
    assert store.entry(cid)["node_count"] == 20


def test_lock_steals_from_dead_owner(tmp_path):
    target = tmp_path / "x"
    Path(str(target) + ".lock").write_text(json.dumps({"pid": 999999, "created": 0}), encoding="utf-8")
    with _FileLock(target, timeout=1.0) as lk:
        assert lk.acquired                                          # dono morto → rouba o lock


def test_lock_does_not_unlink_a_live_others_lock(tmp_path):
    target = tmp_path / "y"
    lockfile = Path(str(target) + ".lock")
    lockfile.write_text(json.dumps({"pid": os.getpid(), "created": time.time()}), encoding="utf-8")  # vivo
    with _FileLock(target, timeout=0.1, stale=9999) as lk:          # não consegue → best-effort, avisa
        assert not lk.acquired
    assert lockfile.exists()                                        # NÃO removeu o lock de outro
