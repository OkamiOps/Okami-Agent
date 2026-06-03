"""Testes da integração de voz no gateway (STT/TTS mockados) + factory."""

from __future__ import annotations

import tempfile

from okami.channels.base import Channel, Inbound
from okami.core import Task, TaskState
from okami.gateway import AgentEndpoint


class VoiceChannel(Channel):
    name = "fake"

    def __init__(self, inbound=None):
        self.sent = []
        self.audio_sent = []
        self._inbound = inbound or []

    def poll(self):
        out, self._inbound = self._inbound, []
        return out

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def send_audio(self, chat_id, path):
        self.audio_sent.append((str(chat_id), path))

    def allowed(self, chat_id):
        return True


class FakeSTT:
    def transcribe(self, path):
        return "qual a previsão do tempo"


class FakeTTS:
    def synthesize(self, text, out):
        from pathlib import Path
        Path(out).write_bytes(b"FAKEAUDIO")
        return out


def _runner(cfg, ws, goal, *, approve=None, extra_context="", cancel=None):
    t = Task(goal=goal)
    t.state, t.result = TaskState.COMPLETE, f"resposta para: {goal}"
    return t


def test_audio_message_is_transcribed_and_handled():
    ch = VoiceChannel(inbound=[Inbound("fake", "7", text="", audio="/tmp/x.ogg")])
    ep = AgentEndpoint("dev", None, tempfile.mkdtemp(), ch, run_task=_runner, stt=FakeSTT(),
                       spawn=lambda fn: fn())
    ep.poll_once()
    texts = [t for _, t in ch.sent]
    assert any("ouvi" in t and "previsão" in t for t in texts)        # transcreveu
    assert any(t.startswith("✅") and "previsão do tempo" in t for t in texts)   # respondeu à transcrição


def test_reply_is_also_sent_as_voice_when_tts_on():
    ch = VoiceChannel()
    ep = AgentEndpoint("dev", None, tempfile.mkdtemp(), ch, run_task=_runner, tts=FakeTTS(),
                       spawn=lambda fn: fn())
    ep.handle("7", "me fale uma piada")
    assert ch.audio_sent and ch.audio_sent[-1][0] == "7"               # mandou áudio também


def test_make_stt_make_tts_disabled_by_default():
    from okami.voice import make_stt, make_tts
    assert make_stt(None) is None and make_stt({"enabled": False}) is None
    assert make_tts(None) is None
