"""Telegram UX — menu '/' (setMyCommands) + reações 👀/👍/👎."""

from __future__ import annotations

import tempfile

from okami.channels.base import Channel, Inbound
from okami.commands import telegram_menu
from okami.core import Task, TaskState
from okami.gateway import AgentEndpoint


def test_telegram_menu_shape_and_excludes_chat_only():
    menu = telegram_menu()
    names = {m["command"] for m in menu}
    assert {"new", "background", "title", "status"} <= names    # comandos reais entram
    assert "exit" not in names                                   # /exit é scope=chat → fora do Telegram
    assert all(not m["command"].startswith("/") and m["description"] for m in menu)
    assert len(menu) <= 100


def test_telegram_channel_start_registers_menu(monkeypatch):
    from okami.channels.telegram import TelegramChannel
    ch = TelegramChannel("TOKEN", allow_chats=[1])
    seen = {}
    monkeypatch.setattr(ch.client, "set_my_commands", lambda cmds: seen.update(n=len(cmds)))
    ch.start()
    assert seen.get("n", 0) > 5


def _runner_ok(cfg, ws, goal, **kw):
    t = Task(goal=goal)
    t.state, t.result = TaskState.COMPLETE, f"feito: {goal}"
    return t


class _ReactChannel(Channel):
    name = "fake"

    def __init__(self):
        self.sent = []
        self.reacts = []
        self._q = [Inbound("fake", "7", text="oi", msg_id="42")]

    def poll(self):
        q, self._q = self._q, []
        return q

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def set_reaction(self, chat_id, message_id, emoji):
        self.reacts.append((str(chat_id), str(message_id), emoji))

    def allowed(self, chat_id):
        return True


def test_reactions_eyes_then_thumbsup_on_success():
    ch = _ReactChannel()
    ep = AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=ch, run_task=_runner_ok,
                       reactions=True, spawn=lambda fn: fn())
    ep.poll_once()
    emojis = [e for _, _, e in ch.reacts]
    assert "👀" in emojis and "👍" in emojis                     # processando → concluído
    assert all(mid == "42" for _, mid, _ in ch.reacts)          # reage na mensagem certa


def test_reactions_off_by_default():
    ch = _ReactChannel()
    ep = AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=ch, run_task=_runner_ok,
                       spawn=lambda fn: fn())                    # reactions default False
    ep.poll_once()
    assert ch.reacts == []                                       # opt-in: nada reage


# ---------------------------------------------------------------- tópicos do Telegram (multi-sessão num chat)
def test_telegram_decode_composite():
    from okami.channels.telegram import TelegramChannel
    assert TelegramChannel._decode("123:5") == ("123", 5)
    assert TelegramChannel._decode("-100999") == ("-100999", None)
    assert TelegramChannel._decode("-100999:7") == ("-100999", 7)


def test_telegram_poll_makes_topic_a_separate_session(monkeypatch):
    from okami.channels.telegram import TelegramChannel
    ch = TelegramChannel("TOK", allow_chats=[123])
    updates = [
        {"update_id": 1, "message": {"chat": {"id": 123}, "text": "root", "message_id": 10}},
        {"update_id": 2, "message": {"chat": {"id": 123}, "text": "no topico", "message_id": 11,
                                     "is_topic_message": True, "message_thread_id": 5}},
    ]
    monkeypatch.setattr(ch.client, "get_updates", lambda offset=0, timeout=30: updates)
    cids = [i.chat_id for i in ch.poll()]
    assert "123" in cids and "123:5" in cids                    # tópico = sessão separada (auto)


def test_telegram_send_and_allowed_route_thread(monkeypatch):
    from okami.channels.telegram import TelegramChannel
    ch = TelegramChannel("TOK", allow_chats=[123])
    sent = []
    monkeypatch.setattr(ch.client, "send_message", lambda chat, text, thread=None: sent.append((chat, thread)))
    ch.send("123:5", "oi")
    ch.send("123", "oi root")
    assert ("123", 5) in sent and ("123", None) in sent         # entrega no tópico certo
    assert ch.allowed("123:5") and ch.allowed("123") and not ch.allowed("999:1")   # allowlist usa o chat real
