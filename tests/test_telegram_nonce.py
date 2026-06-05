"""Nonce na aprovação Telegram (P1.3): o botão amarra ao pedido; clique stale não aprova."""

from __future__ import annotations

import queue

from okami.channels.telegram import TelegramChannel, TelegramClient
from okami.gateway import AgentEndpoint


def test_send_approval_embeds_nonce(monkeypatch):
    c = TelegramClient("tok")
    cap = {}
    monkeypatch.setattr(c, "_call", lambda m, p, **k: (cap.update(p), {})[1])
    c.send_approval("1", "aprovar?", nonce="ab12")
    cbs = [b["callback_data"] for row in cap["reply_markup"]["inline_keyboard"] for b in row]
    assert "okapprove:ab12:yes" in cbs and "okapprove:ab12:no" in cbs


def test_poll_parses_nonce(monkeypatch):
    ch = TelegramChannel("tok", allow_chats=["55"])
    upd = [{"update_id": 1, "callback_query": {"id": "cb", "data": "okapprove:ab12:yes",
            "from": {"id": 55}, "message": {"chat": {"id": 99}}}}]
    monkeypatch.setattr(ch.client, "get_updates", lambda **k: upd)
    monkeypatch.setattr(ch.client, "answer_callback", lambda *a, **k: None)
    assert ch.poll()[0].text == "/yes:ab12"


class _FakeCh:
    def __init__(self):
        self.sent = []

    def allowed(self, cid):
        return True

    def send(self, cid, text):
        self.sent.append(text)


def _bare_ep():
    ep = AgentEndpoint.__new__(AgentEndpoint)        # só o necessário p/ handle() resolver a aprovação
    ep.channel = _FakeCh()
    ep._pending = {}
    return ep


def test_gateway_ignores_stale_nonce_click():
    ep = _bare_ep()
    q: queue.Queue = queue.Queue()
    ep._pending["7"] = (q, "abcd")
    ep.handle("7", "/yes:wrong")                     # nonce de outro pedido → IGNORA
    assert q.empty() and any("expirou" in m for m in ep.channel.sent)
    ep.handle("7", "/yes:abcd")                      # nonce certo → aprova
    assert q.get_nowait() == "/yes"


def test_gateway_accepts_typed_yes_without_nonce():
    ep = _bare_ep()
    q: queue.Queue = queue.Queue()
    ep._pending["7"] = (q, "abcd")
    ep.handle("7", "/yes")                            # digitado (sem nonce) → aceita (compat)
    assert q.get_nowait() == "/yes"


def test_gateway_stale_click_without_pending_is_noop():
    ep = _bare_ep()
    ep.handle("7", "/yes:old")                        # clique dup/stale sem nada pendente
    assert any("nada pendente" in m for m in ep.channel.sent)
