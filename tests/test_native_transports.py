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
    text, finish = from_gemini_response(resp)
    assert text == "resposta final" and finish == "stop"


def test_gemini_response_handles_empty():
    from okami.llm.gemini_native import from_gemini_response
    assert from_gemini_response({"candidates": []}) == ("", "stop")
    assert from_gemini_response({}) == ("", "stop")


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
    text, finish = from_converse_response(resp)
    assert text == "olá mundo" and finish == "stop"


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
