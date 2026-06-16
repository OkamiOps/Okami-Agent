"""#11 Onda 2: reparo multi-passe de argumentos de tool-call malformados (port do Hermes
message_sanitization._repair_tool_call_arguments). Modelo local (GLM/llama.cpp) cospe JSON com vírgula
sobrando, control-char cru, estrutura não-fechada, Python None → proxy dá 400. Repara em vez de crashar."""
from __future__ import annotations

import json


def test_repair_passthrough_valid():
    from okami.llm.json_repair import repair_tool_call_arguments
    assert json.loads(repair_tool_call_arguments('{"a": 1, "b": "x"}')) == {"a": 1, "b": "x"}


def test_repair_empty_and_none_to_empty_obj():
    from okami.llm.json_repair import repair_tool_call_arguments
    assert repair_tool_call_arguments("") == "{}"
    assert repair_tool_call_arguments("   ") == "{}"
    assert repair_tool_call_arguments("None") == "{}"


def test_repair_trailing_comma():
    from okami.llm.json_repair import repair_tool_call_arguments
    assert json.loads(repair_tool_call_arguments('{"a": 1,}')) == {"a": 1}
    assert json.loads(repair_tool_call_arguments('{"l": [1, 2, 3,]}')) == {"l": [1, 2, 3]}


def test_repair_unclosed_structures():
    from okami.llm.json_repair import repair_tool_call_arguments
    assert json.loads(repair_tool_call_arguments('{"a": 1, "b": [2, 3')) == {"a": 1, "b": [2, 3]}


def test_repair_control_chars_in_string():
    from okami.llm.json_repair import repair_tool_call_arguments
    raw = '{"cmd": "line1\nline2\ttabbed"}'        # newline/tab CRU dentro da string
    out = json.loads(repair_tool_call_arguments(raw))
    assert out["cmd"] == "line1\nline2\ttabbed"


def test_repair_unrepairable_to_empty_obj():
    from okami.llm.json_repair import repair_tool_call_arguments
    assert repair_tool_call_arguments("isto não é json de jeito nenhum {{{") == "{}"


# ── integração: _actions_from_tool_calls salva args com vírgula sobrando em vez de virar {} ──
def test_actions_from_tool_calls_repairs_trailing_comma():
    from okami.core.harness.parsing import _actions_from_tool_calls
    acts = _actions_from_tool_calls([{"name": "run_shell", "arguments": '{"cmd": "ls",}'}])
    assert len(acts) == 1 and acts[0].args == {"cmd": "ls"}    # antes: args viravam {} (json.loads falhava)


def test_actions_from_tool_calls_still_skips_truncated():
    from okami.core.harness.parsing import _actions_from_tool_calls
    # args TRUNCADOS (stream cortou no meio, não fecha) → NÃO executa parcial (comportamento preservado)
    acts = _actions_from_tool_calls([{"name": "write_file", "arguments": '{"path": "a.txt", "content": "muito text'}])
    assert acts == []
