"""Tool-calling NATIVO do codex (Onda 3): parse de function_call + tradução p/ o protocolo de ação.

NÃO testa a chamada HTTP ao vivo (precisa do codex logado na máquina do usuário) — testa as PEÇAS
puras: parsing do SSE (terminal e streamed) e a conversão function_call → JSON-em-texto que o harness
parseia. Com `native_tools` OFF (default) nada muda; estes testes cobrem o caminho opt-in.
"""

from __future__ import annotations

from okami.core.harness import parse_action
from okami.core.tools import default_registry
from okami.llm import transports


def test_sse_parses_function_call_from_terminal_output():
    lines = [
        b'data: {"type":"response.completed","response":{"output":[{"type":"function_call",'
        b'"call_id":"c1","name":"write_file","arguments":"{\\"path\\":\\"a.txt\\",\\"content\\":\\"oi\\"}"}],'
        b'"usage":{"input_tokens":5}}}',
    ]
    text, usage, tcs = transports._codex_sse(lines)
    assert text == "" and tcs and tcs[0]["name"] == "write_file"
    assert "a.txt" in tcs[0]["arguments"] and usage == {"input_tokens": 5}


def test_sse_parses_streamed_function_call_with_arg_deltas():
    lines = [
        b'data: {"type":"response.output_item.added","item":{"id":"i1","type":"function_call",'
        b'"call_id":"c1","name":"run_shell","arguments":""}}',
        b'data: {"type":"response.function_call_arguments.delta","item_id":"i1","delta":"{\\"cmd\\":"}',
        b'data: {"type":"response.function_call_arguments.delta","item_id":"i1","delta":"\\"ls\\"}"}',
        b'data: {"type":"response.completed","response":{"output":[],"usage":{}}}',
    ]
    _text, _usage, tcs = transports._codex_sse(lines)
    assert tcs[0]["name"] == "run_shell" and tcs[0]["arguments"] == '{"cmd":"ls"}'


def test_toolcall_translates_to_action_the_harness_parses():
    txt = transports._toolcalls_to_action_text([{"name": "respond", "arguments": '{"message":"oi"}'}])
    action = parse_action(txt)
    assert action is not None and action.tool == "respond" and action.args["message"] == "oi"


def test_responses_tools_are_flat_function_schemas():
    tools = transports._responses_tools(default_registry())
    assert tools and all(t["type"] == "function" and "name" in t and "parameters" in t for t in tools)
    assert all("function" not in t for t in tools)        # FLAT (Responses API), não aninhado


def test_text_only_response_still_parses_to_3_tuple():
    """Sem function_call, segue idêntico ao texto de antes (caminho default)."""
    lines = [b'data: {"type":"response.output_text.delta","delta":"oi"}',
             b'data: {"type":"response.completed","response":{"output":[],"usage":{}}}']
    text, _usage, tcs = transports._codex_sse(lines)
    assert text == "oi" and tcs == []
