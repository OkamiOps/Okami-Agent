"""Paridade Hermes (intermediate-ack): o stream da Responses API emite deltas de RACIOCÍNIO
(response.reasoning_summary_text.delta / reasoning_text.delta) que o Okami ignorava. Agora _codex_sse os
encaminha p/ um callback on_reasoning(delta) — best-effort, vale p/ qualquer endpoint Responses."""
from __future__ import annotations

import json

from okami.llm.transports import _codex_sse


def _sse(*events):
    return [f"data: {json.dumps(e)}".encode() for e in events]


def test_reasoning_deltas_forwarded_to_callback():
    seen = []
    lines = _sse(
        {"type": "response.reasoning_summary_text.delta", "delta": "pensando A"},
        {"type": "response.reasoning_text.delta", "delta": "pensando B"},
        {"type": "response.output_text.delta", "delta": "resposta"},
        {"type": "response.completed", "response": {"usage": {"input_tokens": 1}}},
    )
    text, usage, tcs, finish = _codex_sse(lines, on_reasoning=seen.append)
    assert text == "resposta"                         # texto normal intacto
    assert seen == ["pensando A", "pensando B"]       # ambos os deltas de raciocínio capturados


def test_no_callback_is_safe():
    lines = _sse(
        {"type": "response.reasoning_text.delta", "delta": "x"},
        {"type": "response.output_text.delta", "delta": "ok"},
        {"type": "response.completed", "response": {}},
    )
    text, *_ = _codex_sse(lines)                       # sem callback → não quebra, ignora reasoning
    assert text == "ok"
