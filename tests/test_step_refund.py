"""Item 5 da revisão de harness: execute_code READ-ONLY devolve o passo (meta-trabalho: rodou N tools num
único passo de modelo → não queima o orçamento). BOUNDED (cap = max_poll_waits) p/ não virar loop."""
from __future__ import annotations

import tempfile
from types import SimpleNamespace


def _harness():
    from okami.core.harness.loop import Harness
    from okami.core.harness.models import Task
    return Harness(lambda m, s=None: None, Task(goal="x"), tempfile.mkdtemp())


def _res(out, effect):
    from okami.core.tools.base import ToolResult
    return ToolResult(True, out, effect=effect)


def test_execute_code_readonly_refunds_step():
    from okami.core.harness.models import Task
    h = _harness()
    act = SimpleNamespace(tool="execute_code", args={})
    assert h._handle_tool_result(Task(goal="x"), 5, act, _res("saida", effect=False)) == 5   # devolvido


def test_execute_code_with_effect_counts_normally():
    from okami.core.harness.models import Task
    h = _harness()
    act = SimpleNamespace(tool="execute_code", args={})
    assert h._handle_tool_result(Task(goal="x"), 5, act, _res("escreveu", effect=True)) == 6   # 5→6


def test_other_readonly_tool_not_refunded():
    from okami.core.harness.models import Task
    h = _harness()
    act = SimpleNamespace(tool="read_file", args={})
    assert h._handle_tool_result(Task(goal="x"), 5, act, _res("conteudo", effect=False)) == 6   # só execute_code


def test_refund_is_bounded():
    from okami.core.harness.models import Task
    h = _harness()
    t = Task(goal="x")
    cap = h.budget.max_poll_waits
    step, refunded = 0, 0
    for i in range(cap + 3):
        before = step
        step = h._handle_tool_result(t, step, SimpleNamespace(tool="execute_code", args={"i": i}),
                                     _res(f"out{i}", effect=False))
        if step == before:
            refunded += 1
    assert refunded == cap                                  # exatamente `cap` refunds; depois conta normal
