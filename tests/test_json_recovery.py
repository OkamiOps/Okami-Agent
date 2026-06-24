"""Paridade Hermes (modelo fraco): após N violações de formato (JSON inválido / nenhuma ação), em vez de
DESISTIR seco do turno, o loop injeta uma RECUPERAÇÃO clara e dá rodadas extras — modelo fraco (sem escalate)
que erra o formato 3x merece um empurrão. BOUNDED (não loopa infinito)."""
from __future__ import annotations

from okami.core import Harness, Task, TaskState
from okami.core.tools.registry import default_registry
from okami.llm.usage import Completion


def test_recovery_extends_attempts_then_fails(tmp_path):
    calls = {"n": 0}
    events = []

    def gen(messages, schema=None, **kw):
        calls["n"] += 1
        return Completion(text="blá blá sem nenhuma ação json aqui", tool_calls=[])   # SEMPRE inválido

    h = Harness(gen, Task(goal="conserte o bug X", exit_criteria=[{"type": "file_exists", "path": "x.py"}]),
                tmp_path, registry=default_registry())
    h._emit = lambda k, **kw: events.append(k)
    t = h.run()
    assert t.state == TaskState.FAILED
    assert "json_recovery" in events                  # injetou recuperação antes de falhar
    assert calls["n"] >= 6                             # deu rodadas EXTRAS além das 3 violações iniciais


def test_recovery_lets_turn_survive_past_three_violations(tmp_path):
    calls = {"n": 0}
    events = []
    seq = iter([
        Completion(text="prosa inválida 1", tool_calls=[]),
        Completion(text="prosa inválida 2", tool_calls=[]),
        Completion(text="prosa inválida 3", tool_calls=[]),       # 3 violações → recuperação (não fail)
        Completion(text="", tool_calls=[{"id": "c", "name": "find_files",        # depois ACERTA uma ação real
                                         "arguments": '{"query":"test"}'}]),
        Completion(text="", tool_calls=[{"id": "c2", "name": "task_complete", "arguments": '{"summary":"ok"}'}]),
    ])

    def gen(messages, schema=None, **kw):
        calls["n"] += 1
        return next(seq)

    h = Harness(gen, Task(goal="ache os .py", exit_criteria=[{"type": "file_exists", "path": "x"}]),
                tmp_path, registry=default_registry())
    h._emit = lambda k, **kw: events.append(k)
    h.run()
    assert "json_recovery" in events                  # injetou recuperação às 3 violações
    assert calls["n"] >= 4                             # sobreviveu além das 3 (sem recovery, falharia em 3)
    assert "step" in events                            # uma AÇÃO real (find_files) rodou após a recuperação
