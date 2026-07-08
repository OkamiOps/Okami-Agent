"""FIX 1 (prompt-cache prefix stability): o prefixo ESTÁVEL (identidade/manual/style/tools) tem que vir
ANTES do conteúdo VOLÁTIL (objetivo/critérios da tarefa, workspace ao vivo, extra_block) — senão o
provider nunca acerta o cache_control (system_and_3, providers.py:apply_prompt_caching) porque o
prefixo cacheável diverge a cada turno. Este teste verifica que dois GOALS diferentes (mesma
sessão/model/surface) compartilham um prefixo longo e byte-idêntico."""
from __future__ import annotations

import os

from okami.core.harness.models import Task
from okami.core.harness.prompt import build_system_prompt


def _common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def test_two_different_goals_share_long_stable_prefix():
    t1 = Task(goal="crie um arquivo hello.txt", exit_criteria=[{"type": "file_exists", "path": "hello.txt"}])
    t2 = Task(goal="rode a suíte de testes e relate falhas",
             exit_criteria=[{"type": "shell_ok", "cmd": "pytest -q"}])
    p1 = build_system_prompt(t1, {}, workspace=os.getcwd())
    p2 = build_system_prompt(t2, {}, workspace=os.getcwd())
    prefix = _common_prefix_len(p1, p2)
    # prefixo compartilhado tem que cobrir o bloco de manual/disciplina (bem maior que um preâmbulo curto)
    assert prefix > 2000, f"prefixo compartilhado curto demais ({prefix} chars) — cache vai falhar"
    assert p1[:prefix] == p2[:prefix]
    # o objetivo (volátil) NÃO pode aparecer dentro do prefixo compartilhado
    assert "hello.txt" not in p1[:prefix]
    assert "pytest -q" not in p2[:prefix]


def test_stable_prefix_contains_manual_before_goal():
    t = Task(goal="objetivo qualquer XPTO123", exit_criteria=[{"type": "file_exists", "path": "x.txt"}])
    p = build_system_prompt(t, {}, workspace=os.getcwd())
    idx_manual = p.find("DISCIPLINA DE EXECUÇÃO")
    idx_goal = p.find("XPTO123")
    assert idx_manual != -1 and idx_goal != -1
    assert idx_manual < idx_goal, "manual (estável) precisa vir ANTES do objetivo (volátil) no prompt"


def test_workspace_orientation_moved_to_tail_not_head():
    t = Task(goal="objetivo", exit_criteria=[{"type": "file_exists", "path": "x.txt"}])
    p = build_system_prompt(t, {}, workspace=os.getcwd())
    idx_orient = p.find("ONDE VOCÊ ESTÁ")
    idx_manual = p.find("DISCIPLINA DE EXECUÇÃO")
    assert idx_orient != -1 and idx_manual != -1
    assert idx_orient > idx_manual, "orientação de workspace (volátil, iterdir ao vivo) tem que vir DEPOIS do manual"


def test_conversational_mode_also_keeps_stable_prefix_first():
    t1 = Task(goal="oi, tudo bem?", exit_criteria=[])
    t2 = Task(goal="me ajuda a pensar sobre outra coisa completamente diferente", exit_criteria=[])
    p1 = build_system_prompt(t1, {}, workspace=os.getcwd())
    p2 = build_system_prompt(t2, {}, workspace=os.getcwd())
    prefix = _common_prefix_len(p1, p2)
    assert prefix > 1500, f"prefixo compartilhado curto demais ({prefix} chars) no modo conversa"
