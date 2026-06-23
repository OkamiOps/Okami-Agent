"""Lentidão MORTAL em modelo local (queixa do dono c/ minimax m3): minimax está catalogado em 1M
tokens (janela ARQUITETURAL), mas rodando local no LMStudio essa janela não é servida RÁPIDO. Como a
auto-compaction é proporcional à janela, o teto virava 1M×4×0.72 = 2.88M chars → a compaction NUNCA
disparava → o histórico inteiro era REENVIADO a cada passo (1.5M tok de ENTRADA, cada passo mais lento).

Correção: p/ tier local/weak a janela nominal do catálogo é CAPADA num teto realista, então a compaction
dispara cedo e cada passo fica responsivo. O dono sobe via `context_window:` explícito se quiser mais."""
from __future__ import annotations

from okami.config import ProviderConfig
from okami.llm.providers import compaction_threshold_chars, context_window_tokens


def test_local_tier_caps_nominal_catalog_window():
    pc = ProviderConfig(name="lm", model="openai/minimax-m3", tier="local")
    assert context_window_tokens(pc) == 32_768          # 1M do catálogo NÃO vale p/ local


def test_weak_tier_also_capped():
    pc = ProviderConfig(name="w", model="openai/minimax", tier="weak")
    assert context_window_tokens(pc) <= 32_768


def test_strong_tier_keeps_full_catalog_window():
    pc = ProviderConfig(name="s", model="anthropic/claude-opus-4-8", tier="strong")
    assert context_window_tokens(pc) == 200_000         # cloud forte: janela real preservada


def test_explicit_window_overrides_local_cap():
    pc = ProviderConfig(name="lm", model="openai/minimax", tier="local", context_window=120_000)
    assert context_window_tokens(pc) == 120_000         # dono conhece a janela do LMStudio dele


def test_local_compaction_threshold_is_bounded():
    pc = ProviderConfig(name="lm", model="openai/minimax", tier="local", chars_per_token=4.0)
    assert compaction_threshold_chars(pc) < 100_000      # ~94K, não 2.88M → compaction dispara cedo
