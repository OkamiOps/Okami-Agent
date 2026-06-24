"""Paridade Hermes (multi-vendor): tirar campos ESTRANHOS do objeto-mensagem antes de mandar. Provider
ESTRITO (Mistral/Fireworks/etc) recusa campo extra (reasoning_content/finish_reason ecoado de uma resposta
anterior ou de um replay) → 400. Campos válidos do OpenAI (tool_calls/tool_call_id/name) ficam."""
from __future__ import annotations

from okami.llm.sanitize import sanitize_messages


def test_strips_reasoning_and_finish_reason():
    msgs = [{"role": "assistant", "content": "oi", "reasoning_content": "pensando...",
             "finish_reason": "stop", "reasoning": "x", "_thinking": "y"}]
    out = sanitize_messages(msgs)
    m = out[0]
    assert m["content"] == "oi" and m["role"] == "assistant"
    for bad in ("reasoning_content", "finish_reason", "reasoning", "_thinking"):
        assert bad not in m


def test_keeps_valid_openai_fields():
    msgs = [{"role": "assistant", "content": None,
             "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "resultado", "name": "x"}]
    out = sanitize_messages(msgs)
    assert out[0]["tool_calls"][0]["id"] == "c1"          # tool_calls PRESERVADO (válido)
    assert out[1]["tool_call_id"] == "c1" and out[1]["name"] == "x"


def test_still_sanitizes_content_text():
    msgs = [{"role": "user", "content": "ola\ud800mundo"}]   # surrogate solitário
    assert "\ud800" not in sanitize_messages(msgs)[0]["content"]


def test_clean_message_unchanged():
    msgs = [{"role": "user", "content": "normal"}]
    assert sanitize_messages(msgs) == msgs
