"""Few-shot de UMA chamada preenchida (gap vs Hermes). Modelo fraco imita um EXEMPLO concreto melhor
que regras abstratas — e o exemplo fixa o formato com aspas DUPLAS (o erro #1 do local é aspas simples)."""
from __future__ import annotations

from okami.core import Task
from okami.core.harness.prompt import build_system_prompt
from okami.core.tools.registry import default_registry


def test_prompt_has_concrete_worked_example_with_double_quotes():
    p = build_system_prompt(Task(goal="x"), default_registry(), model="openai/minimax-m3")
    assert "EXEMPLO" in p
    assert '{"tool": "read_file", "args":' in p          # exemplo real, aspas DUPLAS (formato a copiar)
