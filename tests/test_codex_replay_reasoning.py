"""Paridade Hermes (Codex store=false): captura os reasoning items (encrypted_content) do stream e os
RE-EMITE no input da requisição seguinte do MESMO turno, mantendo a cadeia de raciocínio do o-series."""
from __future__ import annotations

import json

from okami.llm.transports import _codex_input_items, _codex_sse


def _sse(*events):
    return [f"data: {json.dumps(e)}".encode() for e in events]


def test_codex_sse_captures_reasoning_items():
    lines = _sse(
        {"type": "response.output_item.done", "item": {"type": "reasoning", "id": "rs_1",
                                                       "encrypted_content": "BLOB1", "summary": ["pensei"]}},
        {"type": "response.output_text.delta", "delta": "resposta"},
        {"type": "response.completed", "response": {"usage": {}}},
    )
    text, usage, tcs, finish, reasoning = _codex_sse(lines)
    assert text == "resposta"
    assert reasoning == [{"id": "rs_1", "encrypted_content": "BLOB1", "summary": ["pensei"]}]


def test_input_items_replays_reasoning_before_message():
    src = [
        {"role": "user", "content": "faça X"},
        {"role": "assistant", "content": "ok", "reasoning_items": [
            {"id": "rs_1", "encrypted_content": "BLOB1", "summary": []}]},
    ]
    items = _codex_input_items(src)
    # reasoning item vem ANTES da msg do assistant; user intacto
    assert items[0] == {"role": "user", "content": "faça X"}
    assert items[1] == {"type": "reasoning", "encrypted_content": "BLOB1", "summary": []}
    assert items[2] == {"role": "assistant", "content": "ok"}


def test_input_items_dedup_and_no_replay_flag():
    src = [{"role": "assistant", "content": "a", "reasoning_items": [
        {"id": "rs_1", "encrypted_content": "B1"}, {"id": "rs_1", "encrypted_content": "B1"}]}]
    assert sum(1 for it in _codex_input_items(src) if it.get("type") == "reasoning") == 1   # dedup por id
    assert all(it.get("type") != "reasoning" for it in _codex_input_items(src, replay_reasoning=False))


def test_sanitize_keeps_reasoning_items_when_strip_fields_false():
    from okami.llm.sanitize import sanitize_messages
    m = [{"role": "assistant", "content": "x", "reasoning_items": [{"id": "r", "encrypted_content": "B"}]}]
    assert "reasoning_items" not in sanitize_messages(m)[0]                 # default: tira (litellm-safe)
    assert sanitize_messages(m, strip_fields=False)[0].get("reasoning_items")   # mantém p/ o codex
