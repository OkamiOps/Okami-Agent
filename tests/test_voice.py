"""Testes da integração de voz no gateway (STT/TTS mockados) + factory."""

from __future__ import annotations
import pytest

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


def _runner(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, **kw):
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
    assert any("previsão do tempo" in t for t in texts)   # respondeu à transcrição (papo: sem selo ✅)


class FirstTimeSTT:
    def __init__(self):
        self._model = None                             # ainda não carregou (1ª vez: instala+baixa modelo)

    def transcribe(self, path):
        self._model = object()
        return "alô mundo"


def test_first_transcription_sends_heads_up():
    """1ª nota de voz dispara install do faster-whisper + download do modelo (lento) → avisa que está
    transcrevendo pra não parecer travado."""
    ch = VoiceChannel(inbound=[Inbound("fake", "7", text="", audio="/tmp/x.ogg")])
    ep = AgentEndpoint("dev", None, tempfile.mkdtemp(), ch, run_task=_runner, stt=FirstTimeSTT(),
                       spawn=lambda fn: fn())
    ep.poll_once()
    texts = [t for _, t in ch.sent]
    assert any("transcrev" in t.lower() for t in texts)               # avisou (não congelado)


def test_audio_without_stt_does_not_drop_silently():
    """Áudio com STT desligado (voice.stt.enabled=false) → avisa o usuário em vez de engolir em silêncio."""
    ch = VoiceChannel(inbound=[Inbound("fake", "7", text="", audio="/tmp/x.ogg")])
    ep = AgentEndpoint("dev", None, tempfile.mkdtemp(), ch, run_task=_runner, stt=None,
                       spawn=lambda fn: fn())
    ep.poll_once()
    texts = [t for _, t in ch.sent]
    assert texts and any("áudio" in t.lower() or "voz" in t.lower() for t in texts)


def test_text_reply_is_not_voiced_by_default():
    """TEXTO → NÃO vira áudio, mesmo com TTS ligado (era o bug do dono: áudio em TODA resposta).
    Áudio ESPELHA a entrada — texto entra, só texto sai."""
    ch = VoiceChannel()
    ep = AgentEndpoint("dev", None, tempfile.mkdtemp(), ch, run_task=_runner, tts=FakeTTS(),
                       spawn=lambda fn: fn())
    ep.handle("7", "me fale uma piada")                               # entrada por TEXTO
    assert not ch.audio_sent                                          # → SEM áudio


def test_voice_input_mirrors_to_voice_reply():
    """Entrada por VOZ (from_voice) → resposta TAMBÉM em áudio (espelha a modalidade)."""
    ch = VoiceChannel()
    ep = AgentEndpoint("dev", None, tempfile.mkdtemp(), ch, run_task=_runner, tts=FakeTTS(),
                       spawn=lambda fn: fn())
    ep.handle("7", "transcrito da nota de voz", from_voice=True)
    assert ch.audio_sent and ch.audio_sent[-1][0] == "7"             # voz entra → voz sai


def test_voice_always_on_voices_even_text():
    """/voice on → SEMPRE áudio, mesmo p/ texto (opt-in explícito do dono)."""
    ch = VoiceChannel()
    ep = AgentEndpoint("dev", None, tempfile.mkdtemp(), ch, run_task=_runner, tts=FakeTTS(),
                       spawn=lambda fn: fn())
    ep.handle("7", "/voice on")
    ep.handle("7", "me fale uma piada")                               # texto, mas voice_always
    assert ch.audio_sent and ch.audio_sent[-1][0] == "7"


def test_stt_on_by_default_tts_opt_in():
    """STT LIGADO por padrão (nota de voz transcreve sem config; faster-whisper auto-instala). TTS é
    OPT-IN (o agente não manda voz sozinho — usa a tool text_to_speech quando faz sentido)."""
    from okami.voice import make_stt, make_tts
    assert make_stt(None) is not None                  # STT default LIGADO
    assert make_stt({"enabled": False}) is None        # opt-out explícito
    assert make_tts(None) is None                      # TTS auto-reply default DESLIGADO
    assert make_tts({"enabled": True}) is not None


def test_make_tts_piper_returns_piper_instance():
    """backend=piper só constrói (sem baixar modelo)."""
    from okami.voice import make_tts
    from okami.voice.tts_local import PiperTTS
    tts = make_tts({"enabled": True, "backend": "piper", "model": "pt_BR-faber-medium"})
    assert isinstance(tts, PiperTTS)
    assert tts.model == "pt_BR-faber-medium"


def test_make_tts_unknown_backend_still_raises():
    from okami.voice import make_tts
    with pytest.raises(ValueError):
        make_tts({"enabled": True, "backend": "naoexiste"})


def test_piper_synthesize_missing_dep_raises_clear_error(monkeypatch):
    """Sem o pacote `piper`, synthesize levanta RuntimeError com a dica de instalação."""
    import builtins
    from okami.voice.tts_local import PiperTTS

    real_import = builtins.__import__

    def _fake_import(name, *args, **kw):
        if name == "piper" or name.startswith("piper."):
            raise ImportError("No module named 'piper'")
        return real_import(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    tts = PiperTTS(model="pt_BR-faber-medium")
    with pytest.raises(RuntimeError) as exc:
        tts.synthesize("olá mundo", "/tmp/okami_piper_test.wav")
    assert "piper-tts" in str(exc.value)


@pytest.fixture(autouse=True)
def _i18n_pt_locale():
    """i18n: estes testes foram escritos com as respostas do gateway em PT. Força o locale `pt` (o
    comportamento EN-default é coberto por test_i18n). Reseta após cada teste."""
    import okami.i18n as _i18n
    _i18n.set_lang("pt")
    yield
    _i18n.set_lang(None)
