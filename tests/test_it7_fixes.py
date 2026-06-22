"""Caça it.7 (find→verify adversarial): TTS não vaza .mp3 em /tmp; MiniMax não grava MP3 vazio; cursor
de chave não cresce sem teto; Whisper rejeita áudio inválido com erro claro. Clusters críticos
(providers retry, loop ReAct) tratados à parte com leitura individual."""
from __future__ import annotations

import io
import urllib.request

import pytest


# ---------------------------------------------------------------- #2 MiniMax 200 sem áudio → erro claro
def test_minimax_tts_raises_on_empty_audio(monkeypatch, tmp_path):
    from okami.voice.tts import MiniMaxTTS

    class _R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _R(b'{"data": {}}'))   # 200 sem audio
    out = tmp_path / "v.mp3"
    with pytest.raises(RuntimeError, match="não retornou áudio"):
        MiniMaxTTS(api_key="x").synthesize("oi", out)
    assert not out.exists()                                  # NÃO cria MP3 vazio


# ---------------------------------------------------------------- #6 cursor de chave normalizado
def test_key_cursor_stays_bounded(monkeypatch, tmp_path):
    import okami.llm.providers as prov
    from okami.config import build_config
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    prov._key_cursor.clear()
    prov._key_cooldown.clear()
    pc = build_config({"default_provider": "p", "providers": {
        "p": {"model": "m", "api_keys": ["k1", "k2", "k3"]}}}).provider("p")
    for _ in range(50):
        prov._rotate_key(pc, now=1000.0)
    assert prov._key_cursor["p"] < 3                         # normalizado ao tamanho do pool, não cresce


# ---------------------------------------------------------------- #16 Whisper rejeita áudio inválido
def test_whisper_rejects_tiny_or_missing_audio(tmp_path):
    from okami.voice.stt import WhisperSTT
    stt = WhisperSTT()
    with pytest.raises(ValueError, match="inválido"):
        stt.transcribe(tmp_path / "nao-existe.wav")         # inexistente → erro, não crash do decoder
    tiny = tmp_path / "tiny.wav"
    tiny.write_bytes(b"RIFF")                                # 4 bytes → curtíssimo
    with pytest.raises(ValueError, match="inválido"):
        stt.transcribe(tiny)


# ---------------------------------------------------------------- #1 TTS não vaza .mp3 temporário
def test_maybe_voice_cleans_temp_file(monkeypatch):
    import glob
    import os
    import tempfile
    from types import SimpleNamespace
    from okami.gateway.endpoint import AgentEndpoint

    created: list[str] = []

    class _TTS:
        def synthesize(self, text, out):
            with open(out, "wb") as f:                       # gera um .mp3 de verdade
                f.write(b"\x00" * 64)
            created.append(out)

    class _Ch:
        def send_audio(self, chat_id, out):
            assert os.path.exists(out)                        # existe DURANTE o envio

    stub = SimpleNamespace(tts=_TTS(), channel=_Ch())
    AgentEndpoint._maybe_voice(stub, "cid", "olá mundo")
    assert created and not os.path.exists(created[0])         # apagado DEPOIS do envio
    assert not glob.glob(os.path.join(tempfile.gettempdir(), "okami_tts_*.mp3")) or \
        created[0] not in glob.glob(os.path.join(tempfile.gettempdir(), "okami_tts_*.mp3"))
