"""audio_analyze (pesquisa #7 item 1) — transcreve áudio do workspace via Whisper LOCAL.

TDD: monkeypatch WhisperSTT.transcribe -> string fixa (sem baixar modelo nem decodificar áudio).
Cobre: transcreve, exige path, arquivo ausente, e check() poda quando faster_whisper falta.
"""
from __future__ import annotations

import importlib.util

from okami.core.tools import ToolContext
from okami.core.tools.audio import AudioAnalyze
from okami.voice import stt as stt_mod


def _ogg(tmp_path):
    p = tmp_path / "nota.ogg"
    p.write_bytes(b"OggS" + b"\x00" * 32)
    return p


def test_tool_transcribes(tmp_path, monkeypatch):
    _ogg(tmp_path)
    monkeypatch.setattr(stt_mod.WhisperSTT, "transcribe", lambda self, path: "olá mundo")
    ctx = ToolContext(workspace=tmp_path)
    res = AudioAnalyze().run({"path": "nota.ogg"}, ctx)
    assert res.ok and "olá mundo" in res.output
    assert res.effect is False
    assert "nota.ogg" in ctx.read_files


def test_tool_silence_returns_placeholder(tmp_path, monkeypatch):
    _ogg(tmp_path)
    monkeypatch.setattr(stt_mod.WhisperSTT, "transcribe", lambda self, path: "")
    res = AudioAnalyze().run({"path": "nota.ogg"}, ToolContext(workspace=tmp_path))
    assert res.ok and res.output  # placeholder não-vazio quando não há fala


def test_tool_requires_path(tmp_path):
    res = AudioAnalyze().run({}, ToolContext(workspace=tmp_path))
    assert not res.ok


def test_tool_missing_file(tmp_path, monkeypatch):
    # não deve nem chamar o whisper se o arquivo não existe
    monkeypatch.setattr(stt_mod.WhisperSTT, "transcribe",
                        lambda self, path: (_ for _ in ()).throw(AssertionError("não devia transcrever")))
    res = AudioAnalyze().run({"path": "sumiu.ogg"}, ToolContext(workspace=tmp_path))
    assert not res.ok


def test_tool_clamps_model(tmp_path, monkeypatch):
    _ogg(tmp_path)
    seen = {}

    class _Spy:
        def __init__(self, model="base", device="cpu", compute_type="int8", language=None):
            seen["model"] = model
            seen["language"] = language

        def transcribe(self, path):
            return "ok"

    monkeypatch.setattr(stt_mod, "WhisperSTT", _Spy)
    AudioAnalyze().run({"path": "nota.ogg", "model": "gigante"}, ToolContext(workspace=tmp_path))
    assert seen["model"] == "base"  # modelo inválido cai no default seguro


def test_tool_honors_language_arg(tmp_path, monkeypatch):
    _ogg(tmp_path)
    seen = {}

    class _Spy:
        def __init__(self, model="base", device="cpu", compute_type="int8", language=None):
            seen["model"] = model
            seen["language"] = language

        def transcribe(self, path):
            return "ok"

    monkeypatch.setattr(stt_mod, "WhisperSTT", _Spy)
    AudioAnalyze().run({"path": "nota.ogg", "model": "small", "language": "pt"},
                       ToolContext(workspace=tmp_path))
    assert seen["model"] == "small" and seen["language"] == "pt"


def test_check_reports_missing_faster_whisper(monkeypatch):
    real = importlib.util.find_spec

    def fake(name, *a, **k):
        return None if name == "faster_whisper" else real(name, *a, **k)

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    reason = AudioAnalyze().check()
    assert reason is not None and "voice" in reason.lower()


def test_check_ok_when_present(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: object())
    assert AudioAnalyze().check() is None
