"""Catálogo de capacidade POR MODELO (models.dev-lite, offline-first — paridade Hermes models_dev.py).

O Hermes consulta models.dev (4000+ modelos) p/ saber janela/vision/custo REAIS. Aqui é a versão
enxuta e honesta: um snapshot embutido dos modelos que aparecem nos nossos presets + os comuns, com
JANELA DE CONTEXTO e VISION. Conservador de propósito — entrada só com número confiável; modelo
desconhecido devolve None e o chamador cai no default por tier (comportamento antigo)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    context_window: int
    vision: bool = False


# Chave = nome NORMALIZADO (sem prefixo de provider, sem :tag, lowercase). O lookup casa por
# "começa com" da chave mais longa → "gpt-5.4-codex" cai em "gpt-5.4", "claude-opus-4-8" exato.
_SNAPSHOT: dict[str, ModelInfo] = {
    # OpenAI
    "gpt-5.5": ModelInfo(400_000, vision=True),
    "gpt-5.4": ModelInfo(400_000, vision=True),
    "gpt-5.3": ModelInfo(400_000, vision=True),
    "gpt-5": ModelInfo(400_000, vision=True),
    "gpt-4.1": ModelInfo(1_000_000, vision=True),
    "gpt-4o": ModelInfo(128_000, vision=True),
    "o3": ModelInfo(200_000, vision=True),
    "o4": ModelInfo(200_000, vision=True),
    # Anthropic
    "claude-opus-4": ModelInfo(200_000, vision=True),
    "claude-sonnet-4": ModelInfo(200_000, vision=True),
    "claude-haiku-4": ModelInfo(200_000, vision=True),
    "claude-fable-5": ModelInfo(200_000, vision=True),
    # Google
    "gemini-3": ModelInfo(1_000_000, vision=True),
    "gemini-2.5": ModelInfo(1_000_000, vision=True),
    "gemma": ModelInfo(128_000),
    # Abertos/API
    "deepseek": ModelInfo(128_000),
    "qwen3.5": ModelInfo(131_072),
    "qwen3": ModelInfo(131_072),
    "glm-5": ModelInfo(128_000),
    "glm-4": ModelInfo(128_000),
    "kimi-k2": ModelInfo(256_000),
    "grok-4": ModelInfo(256_000),
    "minimax": ModelInfo(1_000_000),
    "mistral-large": ModelInfo(128_000),
    "llama-3": ModelInfo(128_000),
    "llama-4": ModelInfo(256_000),
}
# Chaves mais longas primeiro → "gpt-4.1" ganha de "gpt-4", "qwen3.5" de "qwen3".
_KEYS = sorted(_SNAPSHOT, key=len, reverse=True)


def _normalize(model: str) -> str:
    m = (model or "").strip().lower()
    if "/" in m:                                   # "openai-codex/gpt-5.4" → "gpt-5.4"
        m = m.rsplit("/", 1)[-1]
    if ":" in m:                                   # ollama "qwen3.5:27b" → "qwen3.5"
        m = m.split(":", 1)[0]
    return m


def model_info(model: str) -> ModelInfo | None:
    """Capacidade conhecida do modelo (janela/vision), ou None se não estiver no snapshot."""
    m = _normalize(model)
    if not m:
        return None
    for key in _KEYS:
        if m.startswith(key):
            return _SNAPSHOT[key]
    return None


def model_vision(model: str) -> bool:
    """True só p/ modelo CONHECIDO como multimodal (fail-closed: desconhecido = False)."""
    info = model_info(model)
    return bool(info and info.vision)
