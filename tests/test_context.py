"""Testes da estratégia de contexto adaptativa por janela do modelo (§6.4)."""

from __future__ import annotations

from okami.config import ProviderConfig
from okami.llm.providers import compaction_threshold_chars, context_window_tokens
from okami.gateway import _history_block


def test_window_from_explicit_and_tier():
    assert context_window_tokens(ProviderConfig(name="q", model="x", context_window=32768)) == 32768
    # sem context_window → default por tier
    assert context_window_tokens(ProviderConfig(name="c", model="x", tier="strong")) == 128000
    assert context_window_tokens(ProviderConfig(name="l", model="x", tier="local")) == 8192


def test_threshold_scales_with_window():
    small = ProviderConfig(name="q", model="x", context_window=32768)     # Qwen 32K
    big = ProviderConfig(name="c", model="x", context_window=200000)      # Claude 200K
    ts, tb = compaction_threshold_chars(small), compaction_threshold_chars(big)
    assert ts < tb                                  # modelo pequeno comprime MUITO antes
    assert ts == int(32768 * 4.0 * 0.72)
    assert tb == int(200000 * 4.0 * 0.72)


def test_history_block_caps_by_chars():
    history = [("USER", "x" * 500), ("AGENTE", "y" * 500)] * 10   # 20 msgs grandes
    block = _history_block(history, limit=6, max_chars=1200)
    # mantém só o que cabe no cap (mais recente), nunca estoura muito
    assert len(block) < 1600 and "CONVERSA RECENTE" in block
