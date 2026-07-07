"""Orçamento de tool-result ESCALADO pela janela do modelo (porte Hermes tools/budget_config.py
budget_for_context_window). Antes era um teto FIXO (8K por-resultado / 1.5K preview do modelo fraco),
cego à janela real — sub-usava modelo de janela grande e sufocava modelo local com preview migalha.

Cobre: (a) a função pura escala com floor/cap corretos; (b) o Harness resolve a janela do modelo
(model_catalog) e aplica o orçamento escalado em `_tool_result_budget`/`_preview_cap`; (c) o head/tail
passado a `clean_output` não re-clampa abaixo do orçamento escalado."""

from __future__ import annotations

from pathlib import Path

from okami.core.harness.loop import Harness
from okami.core.harness.models import Budget, Task
from okami.core.harness.prompt import budget_for_context_window, format_observation
from okami.core.tools import ToolResult


# ----------------------------------------------------------------- budget_for_context_window (puro)
def test_unknown_window_falls_back_to_historical_defaults():
    per_result, per_turn, preview = budget_for_context_window(0)
    assert per_result == 8_000                 # floor == default histórico (byte-idêntico ao antigo)
    assert per_turn == 200_000                 # == Budget.max_turn_tool_chars default (models.py)
    assert preview == 8_000                    # "muito maior que 1500" (era literal 1500)


def test_small_local_window_hits_the_floor():
    # 8K tokens de janela (modelo local minúsculo) → 8K*4*0.15 = 4800 chars, abaixo do floor de 8000
    per_result, per_turn, preview = budget_for_context_window(8_000)
    assert per_result == 8_000                 # floor, não afunda abaixo do usável
    assert per_turn == 16_000                  # floor do agregado do turno
    assert preview <= per_result


def test_large_window_scales_up_and_is_capped():
    # 200K tokens (Claude/GPT-5-class): window_chars = 800_000; per_result = 15% = 120_000 → CAP 100_000
    per_result, per_turn, preview = budget_for_context_window(200_000)
    assert per_result == 100_000                # cap — nunca passa do histórico "grande"
    assert per_turn == 200_000                  # 30% de 800_000 = 240_000 → CAP 200_000
    assert preview > 8_000                       # escalou pra cima do floor antigo (1500 → 8000 → mais)


def test_mid_window_scales_proportionally_between_floor_and_cap():
    # 40K tokens: window_chars=160_000; per_result=15%=24_000 (entre floor 8K e cap 100K); per_turn=30%=48_000
    per_result, per_turn, preview = budget_for_context_window(40_000)
    assert 8_000 < per_result < 100_000
    assert per_result == 24_000
    assert 16_000 < per_turn < 200_000
    assert per_turn == 48_000
    assert 8_000 <= preview <= per_result       # preview escala mas fica <= o orçamento por-resultado


# ----------------------------------------------------------------- integração no Harness
def _harness(model: str, workspace: Path) -> Harness:
    gen = lambda messages, schema=None: "Vou fazer isso já já."  # noqa: E731 — provider stub, não gera ação
    return Harness(gen, Task(goal="tarefa qualquer"), workspace, model=model)


def test_harness_scales_budget_for_known_large_window_model(tmp_path):
    # "gpt-4.1" está no snapshot do model_catalog com context_window=1_000_000 → cap 100_000/200_000.
    h = _harness("gpt-4.1", tmp_path)
    assert h._tool_result_budget == 100_000
    assert h.budget.max_turn_tool_chars == 200_000


def test_harness_unknown_model_keeps_historical_default(tmp_path):
    h = _harness("modelo-nao-catalogado-xyz", tmp_path)
    assert h._tool_result_budget == 8_000
    assert h.budget.max_turn_tool_chars == 200_000


def test_harness_respects_explicit_budget_override(tmp_path):
    # caller passou um Budget CUSTOM (ex.: guardrails/config) → o harness NÃO pisa no valor explícito
    # com o agregado escalado pela janela (reconcilia com o campo existente, não substitui à força).
    gen = lambda messages, schema=None: "Vou fazer isso já já."  # noqa: E731
    custom = Budget(max_turn_tool_chars=55_555)
    h = Harness(gen, Task(goal="x"), tmp_path, budget=custom, model="gpt-4.1")
    assert h.budget.max_turn_tool_chars == 55_555


# ----------------------------------------------------------------- format_observation head/tail
def test_format_observation_head_tail_follows_result_budget(tmp_path):
    big = "A" * 5_000 + "B" * 5_000            # 10K chars, > default 8K budget
    res = ToolResult(True, big, False)
    # orçamento pequeno (default 8K): head=6000/tail=2000 (75/25) → corta
    small = format_observation(1, "run_shell", res, workspace=tmp_path, result_budget=8_000)
    assert "chars omitidos" in small
    # orçamento GRANDE o bastante p/ caber tudo (>= 10_080 = len+folga do cabeçalho) → NÃO corta
    big_budget = format_observation(2, "run_shell", res, workspace=tmp_path, result_budget=100_000)
    assert "chars omitidos" not in big_budget
    assert "A" * 5_000 in big_budget and "B" * 5_000 in big_budget
