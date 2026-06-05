"""P0.4: o Completion (com tool_calls) é threaded provider→runner→harness — não cai mais p/ res.text."""

from __future__ import annotations

from okami.core import Harness, Task
from okami.llm.usage import Completion


def test_harness_acts_on_native_tool_calls(tmp_path):
    """generate() devolve um Completion COM tool_calls → o harness age por ele (não pelo texto)."""
    def gen(messages, schema=None):
        return Completion(text="", tool_calls=[
            {"id": "c1", "name": "respond", "arguments": '{"message":"oi pelo tool-call nativo"}'}])

    r = Harness(gen, Task(goal="oi"), tmp_path).run()
    assert r.state.value == "COMPLETE" and r.result == "oi pelo tool-call nativo"


def test_harness_still_handles_plain_text_completion(tmp_path):
    """Sem tool_calls, o mesmo caminho (comp.text) funciona como antes — zero regressão."""
    def gen(messages, schema=None):
        return Completion(text='```json\n{"tool":"respond","args":{"message":"oi texto"}}\n```')

    r = Harness(gen, Task(goal="oi"), tmp_path).run()
    assert r.state.value == "COMPLETE" and r.result == "oi texto"


def test_extract_tool_calls_from_litellm_message():
    from okami.llm.providers import _extract_tool_calls

    class _Fn:
        name = "write_file"
        arguments = '{"path":"a.txt"}'

    class _TC:
        id = "c1"
        function = _Fn()

    class _Msg:
        tool_calls = [_TC()]

    assert _extract_tool_calls(_Msg()) == [{"id": "c1", "name": "write_file", "arguments": '{"path":"a.txt"}'}]

    class _Empty:
        tool_calls = None

    assert _extract_tool_calls(_Empty()) == []      # sem function-calling → vazio (caminho de texto)
