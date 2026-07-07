"""WIN3: `spawn` promovido a _CORE_TOOLS — modelo fraco recebe a descrição CHEIA (não a cauda-longa de
1-linha), pra saber DECOMPOR tarefa grande em subtarefas em vez de a tool sumir do repertório prático."""
from __future__ import annotations

from okami.core.harness.prompt import _CORE_TOOLS, build_system_prompt, render_tools_block
from okami.core import Task, default_registry


def test_spawn_is_a_core_tool():
    assert "spawn" in _CORE_TOOLS


def test_weak_model_prompt_keeps_spawn_full_description():
    registry = default_registry()
    assert "spawn" in registry
    block = render_tools_block(registry, model="qwen2.5-7b-instruct")   # tier fraco/local conhecido
    # descrição COMPLETA (não a forma comprimida "- spawn: <70 chars> — args: {...} · detalhes: tool_search(...)")
    spawn_line_idx = next(i for i, ln in enumerate(block.splitlines()) if ln.startswith("- spawn:"))
    lines = block.splitlines()
    full_entry = "\n".join(lines[spawn_line_idx:spawn_line_idx + 2])
    assert 'detalhes: tool_search("spawn")' not in full_entry
    assert registry["spawn"].description[:40] in full_entry


def test_weak_model_prompt_still_compresses_a_non_core_tail_tool():
    """Controle negativo: uma tool de CAUDA LONGA (fora de _CORE_TOOLS) continua comprimida no tier
    fraco — prova que o teste anterior está checando a EXCEÇÃO certa (spawn), não um efeito geral."""
    registry = default_registry()
    tail_tool = next((n for n in registry if n not in _CORE_TOOLS and not getattr(registry[n], "mcp", False)),
                     None)
    assert tail_tool, "esperava ao menos 1 tool de cauda-longa no registry default"
    block = render_tools_block(registry, model="qwen2.5-7b-instruct")
    line = next(ln for ln in block.splitlines() if ln.startswith(f"- {tail_tool}:"))
    assert f'tool_search("{tail_tool}")' in line              # comprimida (cauda longa) — ao contrário do spawn


def test_build_system_prompt_includes_spawn_for_weak_model(tmp_path):
    registry = default_registry()
    task = Task(goal="refatore o projeto inteiro", exit_criteria=[])
    prompt = build_system_prompt(task, registry, workspace=tmp_path, model="qwen2.5-7b-instruct")
    assert registry["spawn"].description[:40] in prompt
