"""Item 1 (#8): primitivo BLOQUEANTE de clarify no gateway — mesma mecânica da aprovação.

A pergunta bloqueia a thread do TURNO (worker); a resposta do dono chega por OUTRA thread (poll/REPL)
via handle(), que destrava a fila. Número → opção; texto livre → passa direto; timeout → None."""
from __future__ import annotations

import tempfile
import threading
import time

from okami.channels.base import Channel
from okami.gateway import AgentEndpoint


class FakeChannel(Channel):
    name = "fake"

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def poll(self):
        return []

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def allowed(self, chat_id):
        return True


def _ep():
    ch = FakeChannel()
    ep = AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=ch,
                       run_task=lambda *a, **k: None, approval_mode="manual", spawn=lambda fn: fn())
    return ep, ch


def _wait(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_clarify_blocks_then_resolves_with_numbered_option():
    ep, ch = _ep()
    out = {}
    th = threading.Thread(target=lambda: out.__setitem__("ans", ep._ask_clarify("42", "A ou B?", ["A", "B"])))
    th.start()
    assert _wait(lambda: bool(ch.sent))
    assert "A ou B?" in ch.sent[-1][1] and "1. A" in ch.sent[-1][1]   # pergunta + menu numerado
    assert _wait(lambda: "42" in ep._clarify_pending)
    ep.handle("42", "2")                              # responde com o NÚMERO da opção
    th.join(timeout=2)
    assert out["ans"] == "B"                          # número → opção
    assert "42" not in ep._clarify_pending            # limpou o pendente


def test_clarify_resolves_with_free_text():
    ep, _ = _ep()
    out = {}
    th = threading.Thread(target=lambda: out.__setitem__("ans", ep._ask_clarify("7", "qual nome?", [])))
    th.start()
    assert _wait(lambda: "7" in ep._clarify_pending)
    ep.handle("7", "minerva")
    th.join(timeout=2)
    assert out["ans"] == "minerva"


def test_clarify_timeout_returns_none():
    ep, _ = _ep()
    ep.clarify_timeout = 0.2                          # timeout curto p/ o teste
    ans = ep._ask_clarify("9", "qual?", [])
    assert ans is None and "9" not in ep._clarify_pending
