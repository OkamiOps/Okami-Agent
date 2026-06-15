"""Telegram-produto P0: split >4096 (sem truncar), retry/backoff (429/5xx), typing."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

from okami.channels.telegram import TelegramChannel, TelegramClient, _split_message


def test_split_no_data_loss():
    t = "\n".join(f"linha {i} " + "x" * 60 for i in range(200))   # bem > 4096
    chunks = _split_message(t, 4000)
    assert len(chunks) > 1 and all(len(c) <= 4000 for c in chunks)
    def squash(s):
        return s.replace(" ", "").replace("\n", "")
    assert "".join(squash(c) for c in chunks) == squash(t)        # nada perdido


def test_send_message_splits(monkeypatch):
    c = TelegramClient("tok")
    sent: list[str] = []
    monkeypatch.setattr(c, "_call", lambda m, p, **k: (sent.append(p["text"]), {"ok": True})[1])
    c.send_message("1", "y" * 9000)
    assert len(sent) >= 3 and all(len(s) <= 4000 for s in sent)   # 3 partes, todas no limite


def test_call_retries_on_429(monkeypatch):
    c = TelegramClient("tok")
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {},
                                         io.BytesIO(json.dumps({"parameters": {"retry_after": 0}}).encode()))
        return io.BytesIO(json.dumps({"ok": True, "result": 7}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    res = c._call("sendMessage", {"chat_id": "1", "text": "x"}, _sleep=lambda s: None)
    assert res["result"] == 7 and calls["n"] == 2                  # tentou de novo após o 429


def test_call_no_retry_on_timeout_for_send(monkeypatch):
    # BUG #9: retry de read-timeout em sendMessage DUPLICA (o Telegram pode já ter recebido).
    import pytest
    c = TelegramClient("tok")
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        raise TimeoutError("read timed out")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(Exception):
        c._call("sendMessage", {"chat_id": "1", "text": "x"}, _sleep=lambda s: None)
    assert calls["n"] == 1                       # NÃO retransmite (1 tentativa) → não duplica


def test_call_retries_timeout_for_idempotent(monkeypatch):
    # getUpdates é idempotente → pode retransmitir em timeout sem efeito colateral.
    c = TelegramClient("tok")
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError("read timed out")
        return io.BytesIO(json.dumps({"ok": True, "result": []}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    res = c._call("getUpdates", {"offset": 0}, _sleep=lambda s: None)
    assert calls["n"] == 2 and res["ok"]         # retransmitiu (sem efeito colateral)


def test_call_retries_connect_refused_for_send(monkeypatch):
    # Conexão recusada = NUNCA chegou ao Telegram → retransmitir sendMessage é seguro (não duplica).
    c = TelegramClient("tok")
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] < 2:
            raise urllib.error.URLError(ConnectionRefusedError("refused"))
        return io.BytesIO(json.dumps({"ok": True, "result": 1}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    res = c._call("sendMessage", {"chat_id": "1", "text": "x"}, _sleep=lambda s: None)
    assert calls["n"] == 2 and res["ok"]


def test_channel_send_typing(monkeypatch):
    ch = TelegramChannel("tok")
    actions: list[tuple] = []
    monkeypatch.setattr(ch.client, "_call",
                        lambda m, p, **k: (actions.append((m, p.get("action"))), {})[1])
    ch.send_typing("1")
    assert ("sendChatAction", "typing") in actions


# ----------------------------------------------------------------- aprovação por botão inline
def test_callback_query_becomes_yes(monkeypatch):
    ch = TelegramChannel("tok", allow_chats=["55"])
    upd = [{"update_id": 1, "callback_query": {"id": "cb", "data": "okapprove:yes",
            "from": {"id": 55}, "message": {"chat": {"id": 99}}}}]
    monkeypatch.setattr(ch.client, "get_updates", lambda **k: upd)
    monkeypatch.setattr(ch.client, "answer_callback", lambda *a, **k: None)
    inb = ch.poll()
    assert len(inb) == 1 and inb[0].text == "/yes" and inb[0].chat_id == "99"


def test_callback_query_unauthorized_clicker_ignored(monkeypatch):
    ch = TelegramChannel("tok", allow_chats=["55"])
    upd = [{"update_id": 1, "callback_query": {"id": "cb", "data": "okapprove:no",
            "from": {"id": 999}, "message": {"chat": {"id": 99}}}}]   # 999 não está na allowlist
    monkeypatch.setattr(ch.client, "get_updates", lambda **k: upd)
    monkeypatch.setattr(ch.client, "answer_callback", lambda *a, **k: None)
    assert ch.poll() == []


def test_send_approval_inline_buttons(monkeypatch):
    c = TelegramClient("tok")
    cap = {}
    monkeypatch.setattr(c, "_call", lambda m, p, **k: (cap.update(method=m, params=p), {})[1])
    c.send_approval("1", "aprovar X?")
    assert cap["method"] == "sendMessage" and "inline_keyboard" in cap["params"]["reply_markup"]
