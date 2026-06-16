"""#10: tool text_to_speech — o agente responde em voz (MEDIA: + bolha de voz)."""
from __future__ import annotations

from types import SimpleNamespace


def test_tts_returns_media_path(monkeypatch, tmp_path):
    from okami.core.tools import ToolContext
    from okami.core.tools import speak as sp
    import okami.voice as voicemod

    class FakeTTS:
        def synthesize(self, text, out):
            from pathlib import Path
            Path(out).write_bytes(b"fakeaudio")
            return out
    monkeypatch.setattr(voicemod, "make_tts", lambda cfg: FakeTTS())
    monkeypatch.setattr(sp, "_to_voice_ogg", lambda p: None)            # sem conversão → entrega o .mp3
    ctx = ToolContext(workspace=tmp_path, cfg=SimpleNamespace(voice={"tts": {"enabled": True}}))
    r = sp.TextToSpeech().run({"text": "olá, dono"}, ctx)
    assert r.ok and r.output.startswith("MEDIA:") and r.output.strip().endswith(".mp3")


def test_tts_voice_bubble_when_ffmpeg(monkeypatch, tmp_path):
    from okami.core.tools import ToolContext
    from okami.core.tools import speak as sp
    import okami.voice as voicemod

    class FakeTTS:
        def synthesize(self, text, out):
            from pathlib import Path
            Path(out).write_bytes(b"x")
            return out
    monkeypatch.setattr(voicemod, "make_tts", lambda cfg: FakeTTS())
    monkeypatch.setattr(sp, "_to_voice_ogg", lambda p: p.with_suffix(".ogg"))   # finge ffmpeg ok
    ctx = ToolContext(workspace=tmp_path, cfg=SimpleNamespace(voice={"tts": {"enabled": True}}))
    r = sp.TextToSpeech().run({"text": "oi"}, ctx)
    assert r.ok and ".ogg" in r.output and "[[audio_as_voice]]" in r.output   # vira bolha de voz


def test_tts_disabled_is_clear(tmp_path):
    from okami.core.tools import ToolContext
    from okami.core.tools.speak import TextToSpeech
    ctx = ToolContext(workspace=tmp_path, cfg=SimpleNamespace(voice={}))
    r = TextToSpeech().run({"text": "oi"}, ctx)
    assert not r.ok and "voice.tts" in r.output


def test_tts_in_registry():
    from okami.core.tools import default_registry
    assert "text_to_speech" in default_registry()
