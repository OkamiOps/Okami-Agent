"""Testes dos transports (sem rede): flatten, split de model, e dispatch routing."""

from __future__ import annotations

from okami.llm import transports
from okami.config import ProviderConfig


def test_flatten_separates_system_and_transcript():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "olá"},
    ]
    system, transcript = transports._flatten(msgs)
    assert system == "sys"
    assert "USER: oi" in transcript and "ASSISTANT: olá" in transcript
    assert "sys" not in transcript


def test_split_model_strips_prefix():
    pc = ProviderConfig(name="claude", model="claude-subscription/claude-opus-4-8")
    assert transports._split_model(pc, None) == "claude-opus-4-8"
    assert transports._split_model(pc, "x/y") == "y"
    assert transports._split_model(pc, "bare") == "bare"


def test_dispatch_returns_none_for_litellm():
    pc = ProviderConfig(name="lm", model="openai/x", transport="litellm")
    assert transports.dispatch(pc, [{"role": "user", "content": "hi"}], None) is None


def test_codex_sse_accumulates_deltas():
    lines = [
        b'event: response.created',
        b'data: {"type":"response.created"}',
        b'data: {"type":"response.output_text.delta","delta":"o"}',
        b'data: {"type":"response.output_text.delta","delta":"i"}',
        b'data: {"type":"response.completed","response":{"output":[]}}',
        b'data: [DONE]',
    ]
    assert transports._codex_sse_text(lines) == "oi"


def test_codex_sse_falls_back_to_completed_output():
    lines = [
        'data: {"type":"response.completed","response":{"output":'
        '[{"content":[{"type":"output_text","text":"oi"}]}]}}',
    ]
    assert transports._codex_sse_text(lines) == "oi"


def test_codex_sse_raises_on_failure_event():
    import pytest
    lines = ['data: {"type":"response.failed","response":{"error":{"message":"x"}}}']
    with pytest.raises(RuntimeError):
        transports._codex_sse_text(lines)
