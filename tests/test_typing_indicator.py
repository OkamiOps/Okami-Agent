"""Bug: o indicador 'digitando…' do Telegram some — era enviado UMA vez (sendChatAction dura ~5s).
Fix: refresher que re-envia a cada ~4s até o turno acabar."""
from __future__ import annotations

import tempfile
import time

from okami.channels.base import Channel
from okami.gateway import AgentEndpoint


class _FakeTelegram(Channel):
    name = "telegram"

    def __init__(self):
        self.typing_calls: list = []

    def poll(self):
        return []

    def send(self, chat_id, text):
        pass

    def allowed(self, chat_id):
        return True

    def send_typing(self, chat_id):
        self.typing_calls.append(chat_id)


class _FakeRest(Channel):           # canal sem send_typing (Slack/Discord/…)
    name = "slack"

    def poll(self):
        return []

    def send(self, chat_id, text):
        pass

    def allowed(self, chat_id):
        return True


def _ep(channel):
    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=channel,
                         run_task=lambda *a, **k: None, approval_mode="manual", spawn=lambda fn: fn())


def test_typing_refreshes_until_stopped():
    ch = _FakeTelegram()
    ep = _ep(ch)
    stop = ep._start_typing("42", interval=0.02)
    assert stop is not None
    time.sleep(0.11)                                   # ~5 ciclos de 0.02s
    stop.set()
    n = len(ch.typing_calls)
    assert n >= 2, f"typing deveria re-enviar várias vezes, foi {n}"   # NÃO é one-shot
    assert all(c == "42" for c in ch.typing_calls)
    time.sleep(0.06)
    assert len(ch.typing_calls) == n                   # parou de verdade após o stop


def test_typing_immediate_first_send():
    ch = _FakeTelegram()
    ep = _ep(ch)
    stop = ep._start_typing("7", interval=5.0)         # intervalo grande: prova que o 1º send é IMEDIATO
    try:
        time.sleep(0.05)
        assert ch.typing_calls == ["7"]                # apareceu na hora, sem esperar o intervalo
    finally:
        stop.set()


def test_typing_none_when_channel_has_no_typing():
    ep = _ep(_FakeRest())
    assert ep._start_typing("1") is None               # canal sem send_typing → não cria thread
