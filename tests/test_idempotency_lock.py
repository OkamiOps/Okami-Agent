"""Idempotência por turno (#3) + lock com start-time / cleanup na saída."""

from __future__ import annotations

import json
import os

from okami.channels.base import Inbound
from okami.gateway import AgentEndpoint
from okami.gateway.sessions import _HELD, _FileLock, _cleanup_held_locks, _proc_start


class _Ch:
    def __init__(self, batch):
        self._batch = batch

    def poll(self):
        return self._batch

    def allowed(self, cid):
        return True

    def send(self, cid, text):
        pass


def _bare_ep(batch):
    ep = AgentEndpoint.__new__(AgentEndpoint)
    ep.channel = _Ch(batch)
    from collections import OrderedDict
    ep._seen_msgs = OrderedDict()
    ep._img = {}
    ep._last_msg_id = {}
    ep.stt = ep.tts = None
    handled = []
    ep.handle = lambda cid, text: handled.append((cid, text))
    return ep, handled


def test_duplicate_msg_id_processed_once():
    dup = Inbound("telegram", "7", text="oi", msg_id="m1")
    ep, handled = _bare_ep([dup])
    ep.poll_once()
    ep.channel._batch = [dup]            # MESMA mensagem entregue de novo (redelivery)
    ep.poll_once()
    assert handled == [("7", "oi")]      # processada UMA vez só (idempotente)


def test_distinct_msg_ids_both_processed():
    ep, handled = _bare_ep([Inbound("telegram", "7", text="a", msg_id="m1"),
                            Inbound("telegram", "7", text="b", msg_id="m2")])
    ep.poll_once()
    assert handled == [("7", "a"), ("7", "b")]


def test_proc_start_is_stable_for_same_process():
    s1, s2 = _proc_start(os.getpid()), _proc_start(os.getpid())
    assert s1 == s2                       # mesmo processo → mesmo start-time (ou '' em macOS/Win)


def test_atexit_cleans_held_lock(tmp_path):
    target = tmp_path / "x"
    with _FileLock(target) as lk:
        assert lk.acquired and str(lk.lock) in _HELD
    assert str(lk.lock) not in _HELD     # __exit__ já removeu
    # simula um lock vazado (não passou pelo __exit__) e roda o cleanup
    leaked = tmp_path / "y.lock"
    leaked.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    _HELD.add(str(leaked))
    _cleanup_held_locks()
    assert not leaked.exists()           # cleanup soltou o lock deste processo
