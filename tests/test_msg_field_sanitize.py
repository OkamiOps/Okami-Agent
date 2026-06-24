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


def test_generic_underscore_prefix_and_extra_keys_stripped():
    from okami.llm.sanitize import sanitize_messages
    msgs = [{
        "role": "assistant", "content": "oi", "tool_calls": [{"id": "c", "type": "function"}],
        "tool_name": "x", "timestamp": 123, "codex_reasoning_items": [{"a": 1}],
        "reasoning_details": [{"b": 2}], "_internal_marker": "drop-me", "_thinking": "secreto",
    }]
    out = sanitize_messages(msgs)[0]
    # campos válidos do OpenAI sobrevivem
    assert out["role"] == "assistant" and out["content"] == "oi" and out["tool_calls"]
    # belt do Hermes: qualquer chave _-prefixada + extras estritos somem (provider estrito 400)
    for bad in ("tool_name", "timestamp", "codex_reasoning_items", "reasoning_details",
                "_internal_marker", "_thinking"):
        assert bad not in out
