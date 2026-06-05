"""Onda 1 (estabilidade): classificador de erro, backoff, codex SSE robusto, complete_messages."""

from __future__ import annotations

import pytest

import okami.llm.providers as prov
from okami.config import build_config
from okami.llm import errors, transports
from okami.llm.retry import jittered_backoff


def _exc(msg, status=None):
    e = RuntimeError(msg)
    if status is not None:
        e.status_code = status
    return e


# ----------------------------------------------------------------- classificador de erro
def test_classify_rate_limit_rotates_and_fallbacks():
    c = errors.classify(_exc("Too Many Requests", 429))
    assert c.reason == "rate_limit" and c.retryable and c.rotate_key and c.fallback


def test_classify_overloaded_does_not_rotate():
    c = errors.classify(_exc("overloaded_error", 529))
    assert c.reason == "overloaded" and c.retryable and not c.rotate_key and c.fallback


def test_classify_bad_request_not_retryable():
    c = errors.classify(_exc("invalid request body", 400))
    assert not c.retryable and not c.rotate_key


def test_classify_content_policy_not_retryable():
    c = errors.classify(_exc("content_policy violation"))
    assert c.reason == "content_policy" and not c.retryable and c.fallback


def test_classify_context_overflow_compresses():
    c = errors.classify(_exc("maximum context length exceeded"))
    assert c.compress and c.retryable


# ----------------------------------------------------------------- backoff
def test_jittered_backoff_doubles_and_caps():
    assert jittered_backoff(1, base_delay=2, max_delay=60, rand=lambda: 0.0) == 2
    assert jittered_backoff(2, base_delay=2, max_delay=60, rand=lambda: 0.0) == 4
    assert jittered_backoff(10, base_delay=2, max_delay=60, rand=lambda: 0.0) == 60   # teto
    assert jittered_backoff(1, base_delay=2, jitter_ratio=0.5, rand=lambda: 1.0) == 3  # +jitter


# ----------------------------------------------------------------- codex SSE robusto
def test_codex_sse_raises_on_empty_no_terminal():
    lines = [b'data: {"type":"response.created"}', b'data: {"type":"response.in_progress"}']
    with pytest.raises(RuntimeError):                          # stream cortado sem terminal nem texto
        transports._codex_sse_text(lines)


def test_codex_sse_ok_with_terminal_and_text():
    lines = ['data: {"type":"response.output_text.delta","delta":"oi"}',
             'data: {"type":"response.completed","response":{"output":[]}}']
    assert transports._codex_sse_text(lines) == "oi"


def test_codex_sse_incomplete_without_text_raises():
    lines = ['data: {"type":"response.incomplete","response":{"incomplete_details":{"reason":"max_output_tokens"}}}']
    with pytest.raises(RuntimeError):
        transports._codex_sse_text(lines)


# ----------------------------------------------------------------- complete_messages
def test_empty_response_triggers_failover(monkeypatch):
    cfg = build_config({"default_provider": "a", "providers": {
        "a": {"model": "ma", "fallback": ["b"]}, "b": {"model": "mb"}}})

    def fake_one(pc, messages, model, schema, overrides):
        return "" if pc.name == "a" else "ok-b"               # 'a' devolve vazio → falha → failover

    monkeypatch.setattr(prov, "_complete_one", fake_one)
    assert prov.complete_messages(cfg, [{"role": "user", "content": "x"}],
                                  _sleep=lambda s: None) == "ok-b"


def test_fallback_skips_unauthenticated_provider(monkeypatch):
    # 'b' exige env key ausente → fallback PULA (não toma 401); cai no 'c' (bare, tentável)
    cfg = build_config({"default_provider": "a", "providers": {
        "a": {"model": "ma", "fallback": ["b", "c"]},
        "b": {"model": "mb", "api_key_env": "X_FALLBACK_KEY_AUSENTE"},
        "c": {"model": "mc"}}})
    monkeypatch.delenv("X_FALLBACK_KEY_AUSENTE", raising=False)
    tried = []

    def fake_one(pc, messages, model, schema, overrides):
        tried.append(pc.name)
        return "" if pc.name == "a" else f"ok-{pc.name}"      # 'a' vazio → failover

    monkeypatch.setattr(prov, "_complete_one", fake_one)
    out = prov.complete_messages(cfg, [{"role": "user", "content": "x"}], _sleep=lambda s: None)
    assert out == "ok-c" and "b" not in tried                 # b pulado (sem auth), c respondeu


def test_non_retryable_400_does_not_burn_pool(monkeypatch):
    cfg = build_config({"default_provider": "a",
                        "providers": {"a": {"model": "ma", "api_keys": ["k1", "k2", "k3"]}}})
    calls = []

    def fake_one(pc, messages, model, schema, overrides):
        calls.append(overrides.get("_api_key"))
        raise _exc("bad request", 400)

    monkeypatch.setattr(prov, "_complete_one", fake_one)
    with pytest.raises(Exception):
        prov.complete_messages(cfg, [{"role": "user", "content": "x"}], _sleep=lambda s: None)
    assert len(calls) == 1                                    # 400 não-retriável → não rotaciona as 3


def test_stream_falls_back_to_robust_path_on_pretoken_failure(monkeypatch):
    # P2: stream que falha ANTES de qualquer token cai no caminho robusto (não deixa o turno em branco).
    cfg = build_config({"default_provider": "a", "providers": {"a": {"model": "ma"}}})

    def boom_stream(**kw):
        raise _exc("502 bad gateway", 502)
    monkeypatch.setattr(prov.litellm, "completion", boom_stream)
    monkeypatch.setattr(prov, "_complete_one", lambda pc, m, model, schema, ov: "resposta-robusta")
    out = "".join(prov.stream_complete(cfg, "oi"))
    assert out == "resposta-robusta"                          # entregou de uma vez, via fallback robusto


def test_stream_empty_also_falls_back(monkeypatch):
    # stream que termina sem produzir nada também é tratado como falha → caminho robusto
    cfg = build_config({"default_provider": "a", "providers": {"a": {"model": "ma"}}})
    monkeypatch.setattr(prov.litellm, "completion", lambda **kw: iter([]))   # zero chunks
    monkeypatch.setattr(prov, "_complete_one", lambda pc, m, model, schema, ov: "ok-robusto")
    assert "".join(prov.stream_complete(cfg, "oi")) == "ok-robusto"


def test_stream_happy_path_yields_tokens(monkeypatch):
    # caminho feliz: streama token-a-token, sem cair no fallback
    cfg = build_config({"default_provider": "a", "providers": {"a": {"model": "ma"}}})

    class _Delta:
        def __init__(self, c):
            self.delta = type("d", (), {"content": c})()

    class _Chunk:
        def __init__(self, c):
            self.choices = [_Delta(c)]
    monkeypatch.setattr(prov.litellm, "completion", lambda **kw: iter([_Chunk("oi"), _Chunk(" mundo")]))
    monkeypatch.setattr(prov, "_complete_one", lambda *a: pytest.fail("não devia cair no fallback"))
    assert "".join(prov.stream_complete(cfg, "x")) == "oi mundo"


def test_complete_messages_scrubs_surrogates(monkeypatch):
    cfg = build_config({"default_provider": "a", "providers": {"a": {"model": "ma"}}})
    seen = {}

    def fake_one(pc, messages, model, schema, overrides):
        seen["content"] = messages[0]["content"]
        return "ok"

    monkeypatch.setattr(prov, "_complete_one", fake_one)
    prov.complete_messages(cfg, [{"role": "user", "content": "oi\ud83dtchau"}], _sleep=lambda s: None)
    assert "\ud83d" not in seen["content"] and "oi" in seen["content"]
