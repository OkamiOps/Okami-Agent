"""Reduz LOOP/erro (sweep #45): vários passos SEM RESULTADO (read/busca vazia, args variando p/ o anti-loop
não pegar) nudgavam p/ SEMPRE até o backstop de passos. Agora o watchdog de sem-progresso é BOUNDED: após
N disparos, escala (modelo mais forte) ou FALHA com salvage — não nudga ∞."""
from __future__ import annotations

from okami.core import Harness, Task, TaskState
from okami.core.tools.base import Tool, ToolResult
from okami.core.tools.registry import default_registry
from okami.llm.usage import Completion


class _NoOp(Tool):
    name = "noop"
    description = "no-op p/ teste"
    args_schema = {"i": "contador"}

    def run(self, args, ctx):
        return ToolResult(True, "(nada encontrado)", effect=False)   # sem efeito + vazio → conta como stall


def test_stall_is_bounded_not_infinite(tmp_path):
    calls = {"n": 0}

    def gen(messages, schema=None):
        calls["n"] += 1                                  # args variam → o anti-loop NÃO pega; isola o stall
        return Completion(text="", tool_calls=[
            {"id": f"c{calls['n']}", "name": "noop", "arguments": '{"i":%d}' % calls["n"]}])

    reg = dict(default_registry())
    reg["noop"] = _NoOp()
    h = Harness(gen, Task(goal="faça algo produtivo"), tmp_path, registry=reg)
    h.budget.stall_limit = 2
    h.budget.max_loop_breaks = 2
    h.budget.max_steps = 200                             # alto: se loopasse, iria longe
    t = h.run()
    assert t.state != TaskState.COMPLETE                 # não concluiu nada
    assert calls["n"] < 20                               # cortou cedo (não foi até o backstop de 200 passos)
