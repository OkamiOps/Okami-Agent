"""Paridade Hermes (Finding 2): quando a resposta é CORTADA pelo limite (finish_reason='length'), a
continuação tem de pedir um teto de tokens MAIOR — senão re-trunca no mesmo ponto e queima as tentativas.
Hermes: `_boost = _boost_base * (n+1)`, cap >= 32768."""
from __future__ import annotations

from okami.core import Harness, Task
from okami.llm.usage import Completion


def test_length_finish_boosts_max_tokens_on_continuation(tmp_path):
    seen = []
    calls = {"n": 0}

    def gen(messages, schema=None, on_token=None, max_tokens=None):
        seen.append(max_tokens)
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(text="relatório longo parte 1…", finish_reason="length")   # CORTADO
        return Completion(text="", tool_calls=[
            {"id": "c", "name": "task_complete", "arguments": '{"summary":"entreguei"}'}])

    h = Harness(gen, Task(goal="escreva um relatório longo"), tmp_path)
    h.run()
    assert seen[0] is None                                  # 1ª chamada: teto default (sem boost)
    assert seen[1] is not None and seen[1] >= 32768        # continuação: teto AUMENTADO (>= 32K, Hermes)


def test_length_boost_grows_with_attempts():
    from okami.core.harness.loop import Harness as H
    h = H(generate=lambda *a, **k: "", task=Task(goal="x"), workspace=".")
    a, b, c = h._length_max_tokens(0), h._length_max_tokens(1), h._length_max_tokens(2)
    assert a >= 32768 and b > a and c > b                  # cresce a cada tentativa
    assert h._length_max_tokens(99) == h._length_max_tokens(98) or h._length_max_tokens(99) <= 200_000  # capado
