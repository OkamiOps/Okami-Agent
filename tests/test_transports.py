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
