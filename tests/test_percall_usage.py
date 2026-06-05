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
