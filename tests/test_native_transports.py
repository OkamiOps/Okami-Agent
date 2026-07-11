"""#12 Onda B: transportes NATIVOS Gemini + Bedrock — prontidão multi-vendor (port Hermes).

Testa o CORE traduzível (OpenAI-msgs ↔ formato nativo) sem SDK/rede; a chamada de SDK é lazy-import.
"""
from __future__ import annotations

from types import SimpleNamespace


# ── Gemini native ──
def test_gemini_contents_translation():
    from okami.llm.gemini_native import to_gemini_request
    req = to_gemini_request([
        {"role": "system", "content": "seja conciso"},
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "olá"},
        {"role": "user", "content": "tudo bem?"},
    ])
    assert req["systemInstruction"]["parts"][0]["text"] == "seja conciso"
    roles = [c["role"] for c in req["contents"]]
    assert roles == ["user", "model", "user"]            # system fora; assistant→model
    assert req["contents"][0]["parts"][0]["text"] == "oi"


def test_gemini_response_extraction():
    from okami.llm.gemini_native import from_gemini_response
    resp = {"candidates": [{"content": {"parts": [{"text": "resposta "}, {"text": "final"}]},
                            "finishReason": "STOP"}]}
    text, finish, tool_calls = from_gemini_response(resp)
    assert text == "resposta final" and finish == "stop" and tool_calls == []


def test_gemini_response_handles_empty():
    from okami.llm.gemini_native import from_gemini_response
    assert from_gemini_response({"candidates": []}) == ("", "stop", [])
    assert from_gemini_response({}) == ("", "stop", [])


def test_gemini_native_uses_supported_http_timeout(monkeypatch):
    import sys
    from types import ModuleType

    from okami.llm import gemini_native

    monkeypatch.setattr("okami.core.lazy_deps.ensure", lambda *args, **kwargs: None)
    captured = {}

    class HttpOptions:
        def __init__(self, **kwargs):
            captured["http_options"] = kwargs

    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.models = self

        def generate_content(self, **kwargs):
            return SimpleNamespace(to_dict=lambda: {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    fake_genai = ModuleType("google.genai")
    fake_genai.Client = Client
    fake_genai.types = SimpleNamespace(HttpOptions=HttpOptions)
    fake_google = ModuleType("google")
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    pc = SimpleNamespace(name="g", model="gemini", api_key="key")
    gemini_native.gemini_native_complete(pc, [{"role": "user", "content": "x"}], None,
                                         overrides={"timeout": 1.25})
    assert captured["http_options"]["timeout"] == 1250


def test_bedrock_native_uses_supported_socket_timeout(monkeypatch):
    import sys
    from types import ModuleType

    from okami.llm import bedrock_native

    monkeypatch.setattr("okami.core.lazy_deps.ensure", lambda *args, **kwargs: None)
    captured = {}

    class Config:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Client:
        def converse(self, **kwargs):
            return {"output": {"message": {"content": [{"text": "ok"}]}}, "stopReason": "end_turn"}

    fake_boto3 = ModuleType("boto3")
    fake_boto3.client = lambda name, **kwargs: (captured.update(kwargs) or Client())
    fake_botocore = ModuleType("botocore")
    fake_botocore_config = ModuleType("botocore.config")
    fake_botocore_config.Config = Config
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setitem(sys.modules, "botocore", fake_botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", fake_botocore_config)

    pc = SimpleNamespace(name="b", model="claude", params={})
    bedrock_native.bedrock_native_complete(pc, [{"role": "user", "content": "x"}], None,
                                           overrides={"timeout": 1.25})
    assert captured["config"].kwargs["read_timeout"] == 1.25


# ── Bedrock native (Converse) ──
def test_bedrock_converse_translation():
    from okami.llm.bedrock_native import to_converse_request
    req = to_converse_request([
        {"role": "system", "content": "regras"},
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": "y"},
    ])
    assert req["system"] == [{"text": "regras"}]
    assert req["messages"] == [{"role": "user", "content": [{"text": "x"}]},
                               {"role": "assistant", "content": [{"text": "y"}]}]


def test_bedrock_response_extraction():
    from okami.llm.bedrock_native import from_converse_response
    resp = {"output": {"message": {"content": [{"text": "olá "}, {"text": "mundo"}]}},
            "stopReason": "end_turn", "usage": {"inputTokens": 10, "outputTokens": 5}}
    text, finish, tool_calls = from_converse_response(resp)
    assert text == "olá mundo" and finish == "stop" and tool_calls == []


# ── tool-calling NATIVO (function calling) — capacidade completa ──
def test_gemini_tools_declaration():
    from okami.llm.gemini_native import to_gemini_request
    tools = [{"type": "function", "function": {"name": "run_shell", "description": "roda",
              "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}}]
    req = to_gemini_request([{"role": "user", "content": "liste"}], tools=tools)
    decls = req["tools"][0]["functionDeclarations"]
    assert decls[0]["name"] == "run_shell" and "parameters" in decls[0]


def test_gemini_extracts_tool_call():
    from okami.llm.gemini_native import from_gemini_response
    resp = {"candidates": [{"content": {"parts": [{"functionCall": {"name": "run_shell", "args": {"cmd": "ls"}}}]},
                            "finishReason": "STOP"}]}
    text, finish, tool_calls = from_gemini_response(resp)
    assert text == "" and len(tool_calls) == 1
    assert tool_calls[0]["name"] == "run_shell"
    import json
    assert json.loads(tool_calls[0]["arguments"]) == {"cmd": "ls"}


def test_bedrock_tools_and_tool_call():
    from okami.llm.bedrock_native import to_converse_request, from_converse_response
    tools = [{"type": "function", "function": {"name": "search", "description": "busca",
              "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}}]
    req = to_converse_request([{"role": "user", "content": "x"}], tools=tools)
    assert req["toolConfig"]["tools"][0]["toolSpec"]["name"] == "search"
    resp = {"output": {"message": {"content": [{"toolUse": {"toolUseId": "t1", "name": "search", "input": {"q": "ok"}}}]}},
            "stopReason": "tool_use"}
    _text, finish, tool_calls = from_converse_response(resp)
    assert finish == "tool_calls" and tool_calls[0]["name"] == "search" and tool_calls[0]["id"] == "t1"


def test_gemini_tool_result_message_translates():
    from okami.llm.gemini_native import to_gemini_request
    msgs = [{"role": "user", "content": "rode"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "run_shell", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "name": "run_shell", "content": "saída"}]
    req = to_gemini_request(msgs)
    # a mensagem de tool vira functionResponse num content
    flat = str(req["contents"])
    assert "functionResponse" in flat and "saída" in flat


# ── dispatch roteia os transportes nativos ──
def test_dispatch_routes_native(monkeypatch):
    from okami.llm import transports
    pc = SimpleNamespace(transport="gemini_native", name="g", model="gemini-3", oauth=None, params={}, api_base="")
    monkeypatch.setattr(transports, "gemini_native_complete", lambda *a, **k: "GEMINI_OK")
    assert transports.dispatch(pc, [{"role": "user", "content": "x"}], None) == "GEMINI_OK"
    pc2 = SimpleNamespace(transport="bedrock_native", name="b", model="claude", oauth=None, params={}, api_base="")
    monkeypatch.setattr(transports, "bedrock_native_complete", lambda *a, **k: "BEDROCK_OK")
    assert transports.dispatch(pc2, [{"role": "user", "content": "x"}], None) == "BEDROCK_OK"
    # litellm segue retornando None (não-interceptado)
    assert transports.dispatch(SimpleNamespace(transport="litellm"), [], None) is None
