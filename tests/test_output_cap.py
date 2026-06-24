"""Paridade Hermes (multi-vendor): NÃO pedir mais output do que cabe na janela. O boost de length subia até
200K tokens SEM cap — num provider de contexto pequeno (Ollama/LMStudio) isso é 400 na hora. Agora o boost é
capado ao disponível ≈ (teto de contexto − prompt atual)/4."""
from __future__ import annotations

from okami.core import Harness, Task
from okami.core.tools.registry import default_registry


def _h(tmp_path):
    return Harness(lambda m, s=None, **k: None, Task(goal="x"), tmp_path, registry=default_registry())


def test_boost_capped_on_small_window(tmp_path):
    h = _h(tmp_path)
    h.budget.max_context_chars = 32000                      # ~8K tokens (modelo de contexto pequeno)
    h.messages = [{"role": "user", "content": "a" * 20000}]  # ~5K tokens já no prompt
    mt = h._length_max_tokens(5)                            # boost cru = 196608
    assert mt < 196608                                      # foi CAPADO
    assert mt <= (32000 - 20000) // 4                       # cabe no que sobra (~3000 tokens)


def test_boost_intact_when_room(tmp_path):
    h = _h(tmp_path)
    h.budget.max_context_chars = 2_000_000                  # janela enorme
    h.messages = [{"role": "user", "content": "oi"}]
    assert h._length_max_tokens(0) == 32768                 # cabe → boost base passa intacto


def test_full_context_asks_minimum(tmp_path):
    h = _h(tmp_path)
    h.budget.max_context_chars = 10000
    h.messages = [{"role": "user", "content": "a" * 40000}]  # prompt já maior que a janela
    assert h._length_max_tokens(3) == 1024                  # contexto cheio → pede o mínimo (compactação age)
