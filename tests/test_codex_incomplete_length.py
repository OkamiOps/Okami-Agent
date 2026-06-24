"""Paridade Hermes (Responses/Codex, agnóstico a qualquer endpoint Responses): quando o status é
"incomplete" por max_output_tokens MAS já veio texto parcial, o Okami entregava cortado como se fosse "stop"
→ a length-continuation (que já funciona pros outros vendors) nunca disparava. Agora mapeia
incomplete/max_output_tokens → finish_reason="length"."""
from __future__ import annotations

import json

from okami.llm.transports import _codex_sse


def _sse(*events):
    return [f"data: {json.dumps(e)}".encode() for e in events]


def test_incomplete_max_output_with_text_is_length():
    lines = _sse(
        {"type": "response.output_text.delta", "delta": "resposta parcial que foi cortada"},
        {"type": "response.incomplete",
         "response": {"incomplete_details": {"reason": "max_output_tokens"}, "usage": {"input_tokens": 5}}},
    )
    text, usage, tool_calls, finish, _rs = _codex_sse(lines)
    assert text == "resposta parcial que foi cortada"
    assert finish == "length"                       # dispara a length-continuation


def test_normal_completed_is_stop():
    lines = _sse(
        {"type": "response.output_text.delta", "delta": "ok"},
        {"type": "response.completed", "response": {"usage": {"input_tokens": 1}}},
    )
    text, usage, tool_calls, finish, _rs = _codex_sse(lines)
    assert text == "ok"
    assert finish in ("stop", "")                    # resposta completa NÃO leva length
