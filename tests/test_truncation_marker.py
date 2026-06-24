"""Paridade Hermes (não entregar pela metade fingindo done): se a continuação de length ESGOTA e a resposta
AINDA vem cortada (finish_reason=length), o relatório entregue leva um AVISO claro de truncamento, em vez de
um 'concluído' silencioso de algo cortado no meio da frase."""
from __future__ import annotations

from okami.core import Harness, Task
from okami.core.tools.registry import default_registry
from okami.llm.usage import Completion


def test_unresolved_truncation_is_flagged(tmp_path):
    def gen(messages, schema=None, **kw):
        return Completion(text="relatório enorme que nunca fecha…", finish_reason="length")  # SEMPRE cortado

    h = Harness(gen, Task(goal="o que é um buraco negro?"), tmp_path, registry=default_registry())
    t = h.run()
    # esgotou as continuações e ainda truncado → entrega COM aviso (não finge done limpo)
    assert "truncad" in (t.result or "").lower() or "truncad" in (t.reason or "").lower()


def test_normal_response_no_marker(tmp_path):
    def gen(messages, schema=None, **kw):
        return Completion(text="resposta curta e completa.", finish_reason="stop")

    h = Harness(gen, Task(goal="oi"), tmp_path, registry=default_registry())
    t = h.run()
    assert "truncad" not in (t.result or "").lower()       # resposta normal não leva aviso
