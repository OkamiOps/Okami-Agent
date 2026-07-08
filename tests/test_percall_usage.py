"""Usage POR CHAMADA no trajeto (P2): cada generate vira um evento llm_call com tokens + trace."""

from __future__ import annotations

from okami.core import Harness, Task
from okami.llm.usage import CanonicalUsage, Completion
from okami.observability.events import read_events


def test_harness_emits_per_call_usage_with_trace(tmp_path):
    def gen(messages, schema=None):
        return Completion(text="", provider="codex", model="gpt-5",
                          usage=CanonicalUsage(input_tokens=2650, output_tokens=20),
                          tool_calls=[{"id": "c1", "name": "respond", "arguments": '{"message":"oi"}'}])

    Harness(gen, Task(goal="oi"), tmp_path).run()
    calls = [e for e in read_events(tmp_path) if e["type"] == "llm_call"]
    assert calls and calls[0]["tokens_in"] == 2650 and calls[0]["tokens_out"] == 20
    assert calls[0]["provider"] == "codex" and calls[0]["model"] == "gpt-5"
    assert calls[0]["tool_call"] is True
    assert calls[0].get("trace")                     # amarrado ao trace_id do turno


def test_text_completion_emits_zero_usage_call(tmp_path):
    """Mesmo sem tokens (provider falso/texto), o trajeto registra a chamada (zerada)."""
    def gen(messages, schema=None):
        return '```json\n{"tool":"respond","args":{"message":"x"}}\n```'   # str → usage zerado

    Harness(gen, Task(goal="oi"), tmp_path).run()
    calls = [e for e in read_events(tmp_path) if e["type"] == "llm_call"]
    assert calls and calls[0]["tokens_in"] == 0 and calls[0]["tool_call"] is False


def test_failed_call_is_not_counted_only_the_successful_retry_is(tmp_path):
    """Uma chamada que ESTOURA (timeout/rede) não vira `llm_call` — só a tentativa que de fato voltou
    com resposta soma tokens. Sem isto, um turno com 1 falha + 1 sucesso contaria tokens 2x (a falha
    nunca consumiu tokens de saída — o provider não devolveu nada). O generate primário FALHA sempre
    (retryable); o harness escala pro `escalate` (§3.5 cascata) — só essa chamada vira evento/tokens."""
    primary_calls = {"n": 0}

    def gen(messages, schema=None):
        primary_calls["n"] += 1
        raise TimeoutError("request timeout")          # sempre falha: SEM usage, nunca deve contar

    def escalate(messages, schema=None):
        return Completion(text="", provider="codex", model="gpt-5",
                          usage=CanonicalUsage(input_tokens=1000, output_tokens=50),
                          tool_calls=[{"id": "c1", "name": "respond", "arguments": '{"message":"oi"}'}])

    Harness(gen, Task(goal="oi"), tmp_path, escalate=escalate).run()
    assert primary_calls["n"] == 1                      # tentou o primário 1x, falhou, escalou (não martelou)
    calls = [e for e in read_events(tmp_path) if e["type"] == "llm_call"]
    assert len(calls) == 1                              # só a chamada BEM-SUCEDIDA (escalada) virou evento
    assert calls[0]["tokens_in"] == 1000 and calls[0]["tokens_out"] == 50   # não duplicado
