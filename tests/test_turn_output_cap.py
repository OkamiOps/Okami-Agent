"""Teto AGREGADO de tool-output por turno (pesquisa #5 item 15, Hermes: 200K chars/turno).

O teto por-resultado (8K) já existia; mas N resultados médios somados ainda inundavam o contexto.
Quando o acumulado do turno passa do teto, outputs passam a ser persistidos com preview CURTO —
mesmo abaixo do teto individual.
"""
from __future__ import annotations

from okami.core import Task
from okami.core.harness import Harness
from okami.core.harness.models import Budget


def test_aggregate_cap_default_is_200k():
    assert Budget().max_turn_tool_chars == 200_000


def test_over_aggregate_cap_persists_medium_outputs(tmp_path):
    (tmp_path / "a.txt").write_text("A" * 3000, encoding="utf-8")
    (tmp_path / "b.txt").write_text("B" * 3000, encoding="utf-8")
    actions = iter([
        '{"tool": "read_file", "args": {"path": "a.txt"}}',
        '{"tool": "read_file", "args": {"path": "b.txt"}}',
        '{"tool": "respond", "args": {"message": "fim"}}',
    ])
    h = Harness(generate=lambda m, s: next(actions), task=Task(goal="oi"), workspace=tmp_path,
                budget=Budget(max_turn_tool_chars=500))      # teto agregado minúsculo p/ o teste
    res = h.run()
    assert res.state.name == "COMPLETE"
    obs = [m["content"] for m in h.messages if m.get("role") == "user" and "OBSERVAÇÃO" in m.get("content", "")]
    assert len(obs) >= 2
    assert "persisted-output" not in obs[0]                  # 1ª leitura (3K < 8K, agregado ok) → inteira
    assert "persisted-output" in obs[1]                      # 2ª: agregado estourou → persistida c/ preview
    assert "AAAA" not in obs[1]                              # e o preview é do arquivo certo (B), curto


def test_under_aggregate_cap_keeps_individual_budget(tmp_path):
    (tmp_path / "a.txt").write_text("A" * 3000, encoding="utf-8")
    actions = iter([
        '{"tool": "read_file", "args": {"path": "a.txt"}}',
        '{"tool": "respond", "args": {"message": "fim"}}',
    ])
    h = Harness(generate=lambda m, s: next(actions), task=Task(goal="oi"), workspace=tmp_path)
    res = h.run()
    assert res.state.name == "COMPLETE"
    obs = [m["content"] for m in h.messages if "OBSERVAÇÃO" in m.get("content", "")]
    assert all("persisted-output" not in o for o in obs)     # 3K < 8K e agregado folgado → nada persiste
