"""Native tool-calling ponta-a-ponta DENTRO do harness (Onda 3): quando o modelo emite function_call
NATIVO, o texto final vem do arg da tool `respond` — SEM envelope ```json``` no texto. Prova o fluxo
no nosso código; o comportamento real do provider exige modelo logado (native_tools: true)."""

from __future__ import annotations

import tempfile

from okami.core import Task, TaskState
from okami.core.harness.loop import Harness
from okami.core.tools.base import Tool, ToolResult, openai_tools
from okami.core.tools.registry import default_registry
from okami.llm.usage import Completion


def _reg():
    return {k: v for k, v in default_registry().items()
            if k in ("respond", "task_complete", "need_input", "read_file", "list_dir")}


def test_native_respond_produces_free_text_answer():
    """tool_call nativo `respond(message=...)` com TEXTO VAZIO no campo text → resposta = o arg, sem JSON."""
    def generate(messages, schema):
        return Completion(text="", finish_reason="tool_calls",
                          tool_calls=[{"id": "1", "name": "respond",
                                       "arguments": '{"message": "Oi! Tudo certo por aqui."}'}])

    t = Harness(generate, Task(goal="oi"), tempfile.mkdtemp(), registry=_reg()).run()
    assert t.state == TaskState.COMPLETE
    assert t.result == "Oi! Tudo certo por aqui."         # texto livre, veio do arg nativo


def test_native_tool_then_respond():
    """Sequência nativa: read_file (tool_call) → OBSERVAÇÃO → respond (tool_call). 2 gerações."""
    calls = {"n": 0}

    class Reader(Tool):
        name = "read_file"
        description = "lê"
        args_schema = {"path": "p"}

        def run(self, args, ctx):
            return ToolResult(True, "conteúdo: 42")

    def generate(messages, schema):
        calls["n"] += 1
        if calls["n"] == 1:
            return Completion(tool_calls=[{"id": "1", "name": "read_file",
                                           "arguments": '{"path": "x.txt"}'}], finish_reason="tool_calls")
        return Completion(tool_calls=[{"id": "2", "name": "respond",
                                       "arguments": '{"message": "o arquivo tem 42"}'}],
                          finish_reason="tool_calls")

    reg = _reg()
    reg["read_file"] = Reader()
    t = Harness(generate, Task(goal="lê o arquivo"), tempfile.mkdtemp(), registry=reg).run()
    assert t.state == TaskState.COMPLETE and t.result == "o arquivo tem 42"
    assert calls["n"] == 2


def test_native_task_complete_with_summary():
    def generate(messages, schema):
        return Completion(tool_calls=[{"id": "1", "name": "task_complete",
                                       "arguments": '{"summary": "feito tudo"}'}],
                          finish_reason="tool_calls")

    t = Harness(generate, Task(goal="faça X"), tempfile.mkdtemp(), registry=_reg()).run()
    assert t.state == TaskState.COMPLETE and t.result == "feito tudo"


# ----------------------------------------------------------------- litellm anexa tools quando native
def test_litellm_attaches_tools_when_native(monkeypatch):
    import okami.llm.providers as P
    from okami.config import ProviderConfig

    captured = {}

    class _Msg:
        content = "ok"
        tool_calls = None

    class _Choice:
        def __init__(self):
            self.message = _Msg()
            self.finish_reason = "stop"

    class _Resp:
        choices = [_Choice()]
        usage = None

    def fake_completion(**kw):
        captured.update(kw)
        return _Resp()

    monkeypatch.setattr(P.litellm, "completion", fake_completion)
    monkeypatch.setattr("okami.llm.native_capability.native_supported", lambda pc: True)   # probe confirmou
    pc = ProviderConfig(name="p", model="openai/x", native_tools=True, tool_choice="auto")
    P._complete_one(pc, [{"role": "user", "content": "hi"}], None, None, {})
    assert "tools" in captured and captured["tool_choice"] == "auto"
    names = [t["function"]["name"] for t in captured["tools"]]
    assert "respond" in names


def test_litellm_no_tools_when_not_native(monkeypatch):
    import okami.llm.providers as P
    from okami.config import ProviderConfig

    captured = {}

    class _Msg:
        content = "ok"
        tool_calls = None

    class _Choice:
        def __init__(self):
            self.message = _Msg()
            self.finish_reason = "stop"

    class _Resp:
        choices = [_Choice()]
        usage = None

    monkeypatch.setattr(P.litellm, "completion", lambda **kw: (captured.update(kw), _Resp())[1])
    # native_tools=False EXPLÍCITO: default agora é None (SMART) e, p/ um modelo/tier desconhecido não
    # sendo local, dispararia o probe de verdade (FIX 1) em vez de assumir 'não suporta' de graça.
    pc = ProviderConfig(name="p", model="openai/x", native_tools=False)
    P._complete_one(pc, [{"role": "user", "content": "hi"}], None, None, {})
    assert "tools" not in captured                          # não envia schemas → protocolo JSON-em-texto


def test_openai_tools_schema_shape():
    schema = openai_tools(_reg())
    assert all(t["type"] == "function" and "name" in t["function"] for t in schema)
