"""Catálogo de capacidade POR MODELO (models.dev-lite, offline): janela de contexto e vision reais
em vez de chute por tier. `context_window: 0` na config passa a resolver pelo modelo; explícito
sempre vence; modelo desconhecido cai no default por tier (comportamento antigo intacto)."""

from __future__ import annotations

from okami.config import ProviderConfig
from okami.llm.model_catalog import model_info, model_vision
from okami.llm.providers import context_window_tokens


def _pc(**kw) -> ProviderConfig:
    kw.setdefault("name", "p")
    kw.setdefault("model", "openai/x")
    return ProviderConfig(**kw)


# ----------------------------------------------------------------- lookup (puro)
def test_lookup_strips_provider_prefix():
    info = model_info("openai-codex/gpt-5.4")
    assert info and info.context_window >= 256_000


def test_lookup_strips_ollama_tag():
    assert model_info("qwen3.5:27b") is not None          # tag :27b não atrapalha


def test_lookup_claude():
    info = model_info("claude-subscription/claude-opus-4-8")
    assert info and info.context_window == 200_000 and info.vision


def test_lookup_gemini_has_big_window():
    info = model_info("gemini-3-pro")
    assert info and info.context_window >= 1_000_000


def test_unknown_model_returns_none():
    assert model_info("modelo-misterioso-9000") is None
    assert model_info("") is None


def test_model_vision():
    assert model_vision("openai/gpt-4o")
    assert model_vision("claude-haiku-4-5")
    assert not model_vision("deepseek-v4")                # texto-only conhecido
    assert not model_vision("modelo-misterioso")          # desconhecido → False (fail-closed p/ vision)


# ----------------------------------------------------------------- integração na janela
def test_context_window_explicit_wins():
    pc = _pc(model="anthropic/claude-opus-4-8", context_window=50_000)
    assert context_window_tokens(pc) == 50_000


def test_context_window_resolves_from_catalog():
    pc = _pc(model="anthropic/claude-opus-4-8", tier="unknown")   # context_window=0 → catálogo
    assert context_window_tokens(pc) == 200_000


def test_context_window_unknown_model_falls_back_to_tier():
    pc = _pc(model="openai/modelo-misterioso", tier="unknown")
    assert context_window_tokens(pc) == 16_000            # default antigo por tier (intacto)
