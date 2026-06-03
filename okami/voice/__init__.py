"""Voz (§13): STT (Whisper local) + TTS (Edge grátis / MiniMax). Tudo opcional."""

from __future__ import annotations


def make_stt(cfg: dict | None):
    """Constrói o STT a partir de voice.stt (None = desativado)."""
    cfg = cfg or {}
    if not cfg.get("enabled"):
        return None
    from okami.voice.stt import WhisperSTT
    return WhisperSTT(model=cfg.get("model", "base"), device=cfg.get("device", "cpu"),
                      compute_type=cfg.get("compute_type", "int8"), language=cfg.get("language"))


def make_tts(cfg: dict | None):
    """Constrói o TTS a partir de voice.tts (None = desativado). backend: edge | minimax."""
    cfg = cfg or {}
    if not cfg.get("enabled"):
        return None
    backend = cfg.get("backend", "edge")
    if backend == "edge":
        from okami.voice.tts import EdgeTTS
        return EdgeTTS(voice=cfg.get("voice", "pt-BR-AntonioNeural"))
    if backend == "minimax":
        from okami.voice.tts import MiniMaxTTS
        return MiniMaxTTS(api_key=cfg.get("api_key"), base_url=cfg.get("api_base", "https://api.minimax.io"),
                          model=cfg.get("model", "speech-02-hd"), voice=cfg.get("voice", "male-qn-qingse"))
    raise ValueError(f"backend de TTS desconhecido: {backend}")
