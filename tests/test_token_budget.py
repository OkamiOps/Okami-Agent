"""Paridade Hermes (multi-vendor): backstop de TOKENS de output por turno. Protege provider POR-TOKEN
(OpenAI/DeepSeek/Qwen/Grok) de um turno disparado (geração gigante repetida) queimar orçamento. Generoso por
default; com cap baixo, esgota → grace (1 última) → FALHA. max_steps pega muitas chamadas; isto pega POUCAS
chamadas GIGANTES."""
from __future__ import annotations

from okami.core import Harness, Task, TaskState
from okami.core.tools.registry import default_registry
from okami.llm.usage import CanonicalUsage, Completion


def test_turn_output_token_budget_fails_runaway(tmp_path):
    calls = {"n": 0}

    def gen(messages, schema=None):
        calls["n"] += 1
        # cada geração: 600 tokens de output, ação que varia (não dispara anti-loop), sem efeito
        return Completion(text="", tool_calls=[
            {"id": f"c{calls['n']}", "name": "find_files", "arguments": '{"pattern":"*%d.py"}' % calls["n"]}],
            usage=CanonicalUsage(output_tokens=600))

    h = Harness(gen, Task(goal="faça algo"), tmp_path, registry=default_registry())
    h.budget.max_turn_output_tokens = 1000        # cap baixo: ~2 chamadas estouram
    h.budget.max_steps = 500                       # alto: não é o step-budget que para
    t = h.run()
    assert t.state != TaskState.COMPLETE
    assert calls["n"] < 8                           # parou cedo pelo budget de tokens (não foi até 500 passos)


def test_default_budget_does_not_trip_normal_turn(tmp_path):
    def gen(messages, schema=None):
        return Completion(text="oi, tudo certo!", tool_calls=[], usage=CanonicalUsage(output_tokens=200))

    h = Harness(gen, Task(goal="oi"), tmp_path, registry=default_registry())
    t = h.run()
    assert t.state == TaskState.COMPLETE            # turno normal (200 tokens) não chega perto do default 4M
