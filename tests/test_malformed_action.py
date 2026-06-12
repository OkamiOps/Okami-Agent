"""Reparo de tool-call MALFORMADA (pesquisa #5 item 8, paridade Hermes _repair_tool_call).

O rename fuzzy de tool alucinada já existia. Aqui: (1) JSON inválido não é descartado MUDO — vira
erro sintético que ENSINA o formato; (2) JSON truncado (não fecha }/]) é detectado e NUNCA executado
— nem no protocolo texto (não parseia) nem no nativo (args parciais não viram {}).
"""
from __future__ import annotations

from okami.core import Task
from okami.core.harness import Harness
from okami.core.harness.parsing import (
    _actions_from_tool_calls, detect_malformed, truncated_action_tail,
)


# ------------------------------------------------------------------ truncated_action_tail
def test_truncated_action_detected():
    assert truncated_action_tail('```json\n{"tool": "write_file", "args": {"path": "a", "content": "aa')


def test_complete_action_not_truncated():
    assert not truncated_action_tail('{"tool": "respond", "args": {"message": "oi"}}')


def test_prose_with_brace_not_truncated():
    assert not truncated_action_tail("use {placeholder} no template e siga")


# ------------------------------------------------------------------ detect_malformed
def test_invalid_json_yields_teaching_error():
    diag = detect_malformed('```json\n{"tool": "read_file", "args": {path: "a.txt"}}\n```')
    assert diag is not None
    assert "INVÁLIDO" in diag and "aspas DUPLAS" in diag


def test_truncated_json_yields_reemit_smaller():
    diag = detect_malformed('{"tool": "write_file", "args": {"content": "aaaa')
    assert diag is not None
    assert "TRUNCADO" in diag and "NÃO re-emita igual" in diag


def test_plain_prose_yields_none():
    assert detect_malformed("só uma frase qualquer, sem tentativa de ação") is None


# ------------------------------------------------------------------ native tool_calls truncados
def test_native_truncated_args_do_not_execute():
    acts = _actions_from_tool_calls([{"name": "write_file", "arguments": '{"path": "a", "content": "aa'}])
    assert acts == []                                # parcial NÃO executa (antes virava args={})


def test_native_invalid_but_closed_args_fall_back_to_empty():
    acts = _actions_from_tool_calls([{"name": "list_dir", "arguments": '{bad json}'}])
    assert len(acts) == 1 and acts[0].args == {}     # malformado mas FECHADO → comportamento antigo


# ------------------------------------------------------------------ harness ensina no re-prompt
def test_harness_teaches_on_invalid_json(tmp_path):
    seen = []

    def gen(messages, schema):
        if not seen:
            seen.append("x")
            return '```json\n{"tool": "read_file", "args": {path: "a.txt"}}\n```'
        seen.append(messages[-1]["content"])
        return '{"tool": "respond", "args": {"message": "fim"}}'

    h = Harness(generate=gen, task=Task(goal="oi"), workspace=tmp_path)
    res = h.run()
    assert res.state.name == "COMPLETE"
    assert "INVÁLIDO" in seen[1]                     # re-prompt ensinou, não só "REJEITADO" genérico
