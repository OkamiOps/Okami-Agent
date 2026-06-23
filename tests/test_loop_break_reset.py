"""Paridade Hermes: uma tarefa LONGA e produtiva não pode acumular loop-breaks de FASES DISTINTAS num
_fail prematuro. Mutação bem-sucedida (effect=True) = progresso real → solta o budget de loop. Loop
patológico (só leitura/sem efeito) NÃO solta → segue pego."""
from __future__ import annotations

from okami.core import Harness, Task
from okami.core.harness.parsing import Action
from okami.core.tools.base import ToolResult


def _h(tmp_path):
    h = Harness(generate=lambda *a, **k: "", task=Task(goal="x"), workspace=tmp_path)
    h.messages = []
    h._obs_chars = 0
    return h


def test_effectful_step_resets_loop_breaks(tmp_path):
    h = _h(tmp_path)
    h._loop_breaks = 2
    h._handle_tool_result(h.task, 0, Action("write_file", {"path": "a"}), ToolResult(True, "ok", effect=True))
    assert h._loop_breaks == 0                              # progresso REAL → budget de loop solto


def test_readonly_step_does_not_reset_loop_breaks(tmp_path):
    h = _h(tmp_path)
    h._loop_breaks = 2
    h._handle_tool_result(h.task, 0, Action("read_file", {"path": "a"}), ToolResult(True, "conteúdo", effect=False))
    assert h._loop_breaks == 2                              # leitura não solta → loop de leitura segue pego
