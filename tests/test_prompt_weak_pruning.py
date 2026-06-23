"""Prompt enxuto p/ modelo LOCAL fraco (gap #3 vs Hermes). 66 tools com descrição inteira = ~6K tokens
que um modelo 8-32B não segura na atenção → alucina nome de tool / conversa em vez de agir. Hermes manda
um set pequeno e difere o resto via tool_search. Aqui, p/ tier fraco/aberto, as tools de CAUDA LONGA
viram 1-linha (nome + args + ponteiro tool_search), e as do núcleo (arquivo/shell/memória/terminais)
seguem inteiras. Modelo forte: sem poda (prompt completo)."""
from __future__ import annotations

from okami.core import Task
from okami.core.harness.prompt import build_system_prompt
from okami.core.tools.registry import default_registry


def test_weak_model_gets_smaller_prompt_with_tool_search_pointers():
    reg, t = default_registry(), Task(goal="faça uma tarefa")
    weak = build_system_prompt(t, reg, model="openai/minimax-m3")
    strong = build_system_prompt(t, reg, model="anthropic/claude-opus-4-8")
    assert len(weak) < len(strong) * 0.9                    # meaningfully menor
    assert weak.count('tool_search("') >= 5                 # cauda longa virou ponteiro
    for core in ("read_file", "run_shell", "respond", "write_file", "edit_file"):
        assert core in weak                                 # núcleo continua presente e chamável


def test_strong_model_keeps_full_prompt():
    reg, t = default_registry(), Task(goal="x")
    strong = build_system_prompt(t, reg, model="anthropic/claude-opus-4-8")
    assert 'tool_search("' not in strong                    # sem poda por tier no forte


def test_unknown_model_is_not_pruned():
    reg, t = default_registry(), Task(goal="x")
    unknown = build_system_prompt(t, reg, model="")
    assert 'tool_search("' not in unknown                   # desconhecido = comportamento antigo (sem poda)
