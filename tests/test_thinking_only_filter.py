"""Paridade Hermes (multi-vendor reasoning): turnos SÓ-DE-THINKING (assistant sem tool_calls e sem texto, ou
o placeholder '(resposta vazia)') são DROPADOS da cópia mandada ao provider (Hermes _drop_thinking_only),
mesclando users adjacentes p/ preservar alternância. Modelo de reasoning (minimax/DeepSeek) não deixa
assistant vazio bloatando contexto / dando 400. NÃO muta o histórico persistido."""
from __future__ import annotations

from okami.core.harness.loop import _filter_thinking_only


def test_drops_empty_placeholder_assistant():
    msgs = [{"role": "user", "content": "oi"},
            {"role": "assistant", "content": "(resposta vazia)"},
            {"role": "user", "content": "ainda aí?"}]
    out = _filter_thinking_only(msgs)
    assert all(m.get("content") != "(resposta vazia)" for m in out)
    assert len(out) == 1 and out[0]["role"] == "user"          # 2 users adjacentes mesclados


def test_drops_blank_assistant_no_toolcalls():
    msgs = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "   "}]
    assert all(m.get("role") != "assistant" for m in _filter_thinking_only(msgs))


def test_keeps_assistant_with_tool_calls():
    msgs = [{"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1", "content": "r"}]
    out = _filter_thinking_only(msgs)
    assert out[0].get("tool_calls")                            # tem tool_calls → NÃO é thinking-only


def test_keeps_real_assistant_text():
    msgs = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "resposta de verdade"}]
    assert _filter_thinking_only(msgs) == msgs                 # nada a dropar


def test_does_not_mutate_input():
    msgs = [{"role": "assistant", "content": "(resposta vazia)"}]
    _filter_thinking_only(msgs)
    assert msgs[0]["content"] == "(resposta vazia)"            # original intacto
