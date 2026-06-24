"""Paridade Hermes (UX): clarify com OPÇÕES discretas vira BOTÕES inline no Telegram — o dono TOCA em vez de
digitar o número. O clique vira o NÚMERO da opção, que o endpoint já mapeia p/ o texto (reusa a resolução do
clarify pendente). Canal sem send_clarify cai no menu de texto (comportamento antigo)."""
from __future__ import annotations

from okami.channels.telegram import TelegramChannel, TelegramClient
from okami.gateway import AgentEndpoint


def test_client_send_clarify_one_button_per_option(monkeypatch):
    c = TelegramClient("tok")
    cap = {}
    monkeypatch.setattr(c, "_call", lambda m, p, **k: (cap.update(p), {})[1])
    c.send_clarify("1", "Qual ambiente?", ["produção", "staging"])
    cbs = [b["callback_data"] for row in cap["reply_markup"]["inline_keyboard"] for b in row]
    assert cbs == ["okclarify:0", "okclarify:1"]


def test_poll_clarify_callback_emits_option_number(monkeypatch):
    ch = TelegramChannel("tok", allow_chats=["55"])
    upd = [{"update_id": 1, "callback_query": {"id": "cb", "data": "okclarify:1",
            "from": {"id": 55}, "message": {"chat": {"id": 99}}}}]
    monkeypatch.setattr(ch.client, "get_updates", lambda **k: upd)
    monkeypatch.setattr(ch.client, "answer_callback", lambda *a, **k: None)
    assert ch.poll()[0].text == "2"            # idx 1 → opção nº 2 (handle() mapeia p/ o texto)


def test_poll_approval_callback_still_works(monkeypatch):
    ch = TelegramChannel("tok", allow_chats=["55"])
    upd = [{"update_id": 1, "callback_query": {"id": "cb", "data": "okapprove:ab12:yes",
            "from": {"id": 55}, "message": {"chat": {"id": 99}}}}]
    monkeypatch.setattr(ch.client, "get_updates", lambda **k: upd)
    monkeypatch.setattr(ch.client, "answer_callback", lambda *a, **k: None)
    assert ch.poll()[0].text == "/yes:ab12"    # aprovação não regrediu


def test_ask_clarify_uses_buttons_when_channel_supports_it():
    ep = AgentEndpoint.__new__(AgentEndpoint)
    calls = []

    class _Ch:
        def send_clarify(self, cid, text, options): calls.append(("buttons", cid, list(options)))
        def send(self, cid, text): calls.append(("plain", text))

    ep.channel = _Ch()
    ep._clarify_pending = {}
    ep.clarify_timeout = 0.01
    ans = ep._ask_clarify("9", "Qual?", ["a", "b"])
    assert ans is None                          # ninguém respondeu → timeout
    assert calls and calls[0][0] == "buttons" and calls[0][2] == ["a", "b"]


def test_ask_clarify_falls_back_to_text_without_send_clarify():
    ep = AgentEndpoint.__new__(AgentEndpoint)
    calls = []

    class _Ch:
        def send(self, cid, text): calls.append(text)

    ep.channel = _Ch()
    ep._clarify_pending = {}
    ep.clarify_timeout = 0.01
    ep._ask_clarify("9", "Qual?", ["a", "b"])
    assert any("Qual?" in c for c in calls)     # caiu no menu de texto
