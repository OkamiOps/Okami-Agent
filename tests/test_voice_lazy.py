"""Voz embutida sem o usuário pré-instalar nada (§13). O stack de voz já existia, mas:
  - make_stt só construía STT se voice.stt.enabled (default OFF) → nota de voz era DESCARTADA em silêncio;
  - WhisperSTT/EdgeTTS faziam `import faster_whisper/edge_tts` cru → falhava sem o extra `[voice]`.
Fix: STT LIGADO por padrão + auto-install (lazy_deps.ensure) do faster-whisper/edge-tts na 1ª vez."""
from __future__ import annotations

import pytest


def test_lazy_deps_has_stt_whisper():
    from okami.core.lazy_deps import LAZY_DEPS
    assert "stt.whisper" in LAZY_DEPS                  # allowlist cobre o auto-install do STT
    assert any("faster-whisper" in s for s in LAZY_DEPS["stt.whisper"])


def test_make_stt_on_by_default():
    from okami.voice import make_stt
    assert make_stt(None) is not None                 # default LIGADO → áudio funciona sem config
    assert make_stt({}) is not None
    assert make_stt({"enabled": False}) is None       # opt-out explícito ainda desliga


def test_whisper_load_ensures_dep_before_import(monkeypatch):
    """_load() chama ensure('stt.whisper') ANTES de importar faster_whisper (auto-install na 1ª vez)."""
    import okami.voice.stt as stt_mod
    from okami.core.lazy_deps import FeatureUnavailable

    def _boom(feat, **k):
        assert feat == "stt.whisper"                   # feature certa
        raise FeatureUnavailable(feat, ("faster-whisper>=1.0",), "test")
    monkeypatch.setattr("okami.core.lazy_deps.ensure", _boom)
    with pytest.raises(FeatureUnavailable):
        stt_mod.WhisperSTT()._load()


def test_edge_tts_ensures_dep_before_import(monkeypatch, tmp_path):
    """EdgeTTS.synthesize chama ensure('tts.edge') ANTES de importar edge_tts."""
    import okami.voice.tts as tts_mod
    from okami.core.lazy_deps import FeatureUnavailable

    def _boom(feat, **k):
        assert feat == "tts.edge"
        raise FeatureUnavailable(feat, ("edge-tts>=7.0.0",), "test")
    monkeypatch.setattr("okami.core.lazy_deps.ensure", _boom)
    with pytest.raises(FeatureUnavailable):
        tts_mod.EdgeTTS().synthesize("oi", tmp_path / "o.mp3")


def test_audio_tool_available_when_lazy_install_on(monkeypatch):
    """audio_analyze NÃO se poda quando lazy-install está ligado (vai instalar no run)."""
    monkeypatch.setattr("okami.core.lazy_deps._allow_lazy_installs", lambda: True)
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda n: None)   # finge faster_whisper ausente
    from okami.core.tools.audio import AudioAnalyze
    assert AudioAnalyze().check() is None              # disponível (lazy instala no run)


def test_speak_tool_available_when_lazy_install_on(monkeypatch):
    monkeypatch.setattr("okami.core.lazy_deps._allow_lazy_installs", lambda: True)
    import builtins
    real_import = builtins.__import__

    def _no_edge(name, *a, **k):
        if name == "edge_tts":
            raise ImportError("no edge_tts")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _no_edge)
    from okami.core.tools.speak import TextToSpeech
    assert TextToSpeech().check() is None              # disponível (lazy instala no run)
