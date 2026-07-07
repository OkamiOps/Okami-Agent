"""Velocidade em modelo LOCAL: o custo por-passo é a OBSERVAÇÃO nova reenviada. Uma saída grande de tool
ficava com preview INLINE de 8K (o resto já ia pro disco). P/ tier fraco/local encolhemos o preview
(full segue no disco, relido com read_file/offset) → cada passo processa MENOS contexto que o modelo
forte (janela grande, preview cheio). O orçamento ESCALA com a janela real do modelo (budget_for_context_
window) — pra um modelo aberto/local sem janela catalogada ou capada em 32K (_LOCAL_WINDOW_CAP), o
preview fica no floor (8K, bem acima do antigo fixo de 1.5K, mas ainda MENOR que o do modelo forte).
Saída pequena (<8K) segue inteira (read_file não sofre)."""
from __future__ import annotations

from okami.core import Harness, Task
from okami.core.harness.parsing import Action
from okami.core.tools.base import ToolResult


def _harness(tmp_path, model):
    h = Harness(generate=lambda *a, **k: "", task=Task(goal="x"), workspace=tmp_path, model=model)
    h.messages = []
    h._obs_chars = 0
    return h


def test_weak_model_gets_short_inline_preview(tmp_path):
    h = _harness(tmp_path, "openai/minimax-m3")
    h._append_observation(1, Action("run_shell", {"cmd": "x"}), ToolResult(True, "L" * 20000, effect=False))
    body = h.messages[-1]["content"]
    # preview escala pela janela (floor ~8K, bem acima do antigo fixo 1.5K) mas continua ENXUTO frente
    # à saída de 20K e ao preview cheio do modelo forte (test_strong_model_keeps_full_preview).
    assert len(body) < 9000
    assert ".okami/tool_outputs" in body or "read_file" in body   # full no disco, com ponteiro p/ reler


def test_strong_model_keeps_full_preview(tmp_path):
    h = _harness(tmp_path, "anthropic/claude-opus-4-8")
    h._append_observation(1, Action("run_shell", {"cmd": "x"}), ToolResult(True, "L" * 20000, effect=False))
    assert len(h.messages[-1]["content"]) > 6000            # forte mantém preview cheio


def test_small_output_stays_full_even_for_weak(tmp_path):
    h = _harness(tmp_path, "openai/minimax-m3")
    h._append_observation(1, Action("read_file", {"path": "a"}), ToolResult(True, "L" * 3000, effect=False))
    assert "L" * 3000 in h.messages[-1]["content"]          # <8K não é truncado (read_file pequeno intacto)
