"""Retry reativo de grammar-400 (paridade Hermes): se o schema de uma tool tropeça no grammar-converter
MESMO após a sanitização proativa, re-sanitiza AGRESSIVO (tira enum/const/limites) e retenta 1x — em vez
de matar o turno. Erro que NÃO é de schema (rate/auth) NÃO retenta aqui."""
from __future__ import annotations

import pytest

from okami.llm.schema_sanitizer import sanitize_tool_schema


def test_aggressive_strips_enum_const_and_limits():
    src = {"type": "string", "enum": ["a", "b"], "minLength": 1, "maxLength": 9}
    out = sanitize_tool_schema(src, aggressive=True)
    assert "enum" not in out and "minLength" not in out and "maxLength" not in out


def test_non_aggressive_keeps_enum():
    out = sanitize_tool_schema({"type": "string", "enum": ["a", "b"]}, aggressive=False)
    assert out.get("enum") == ["a", "b"]                    # padrão preserva (enum é válido p/ a maioria)


class _Msg:
    content = "ok"
    tool_calls = None
    reasoning_content = None


class _Choice:
    message = _Msg()
    finish_reason = "stop"


class _Resp:
    choices = [_Choice()]
    usage = None


def test_grammar_error_triggers_aggressive_retry(monkeypatch):
    import okami.llm.providers as P
    from okami.config import ProviderConfig
    monkeypatch.setattr("okami.llm.native_capability.native_supported", lambda pc: True)
    calls = []

    def fake(**kw):
        calls.append(kw)
        if len(calls) == 1:
            raise RuntimeError("grammar error: failed to parse schema for tool 'x'")
        return _Resp()
    monkeypatch.setattr(P.litellm, "completion", fake)
    pc = ProviderConfig(name="p", model="openai/gpt-5.4", native_tools=True)
    res = P._complete_one(pc, [{"role": "user", "content": "hi"}], None, None, {})
    assert res.text == "ok" and len(calls) == 2            # retentou 1x e funcionou
    assert "tools" in calls[1]                             # 2ª chamada ainda manda tools (re-sanitizadas)


def test_non_schema_error_does_not_retry(monkeypatch):
    import okami.llm.providers as P
    from okami.config import ProviderConfig
    monkeypatch.setattr("okami.llm.native_capability.native_supported", lambda pc: True)
    calls = []

    def fake(**kw):
        calls.append(kw)
        raise RuntimeError("rate limit exceeded (429)")
    monkeypatch.setattr(P.litellm, "completion", fake)
    pc = ProviderConfig(name="p", model="openai/gpt-5.4", native_tools=True)
    with pytest.raises(RuntimeError):
        P._complete_one(pc, [{"role": "user", "content": "hi"}], None, None, {})
    assert len(calls) == 1                                 # erro não-schema → NÃO retenta aqui (sobe pro failover)
