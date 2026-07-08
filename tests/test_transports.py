"""Testes dos transports (sem rede): flatten, split de model, e dispatch routing."""

from __future__ import annotations

from okami.llm import transports
from okami.config import ProviderConfig


def test_flatten_separates_system_and_transcript():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "olá"},
    ]
    system, transcript = transports._flatten(msgs)
    assert system == "sys"
    assert "USER: oi" in transcript and "ASSISTANT: olá" in transcript
    assert "sys" not in transcript


def test_split_model_strips_prefix():
    pc = ProviderConfig(name="claude", model="claude-subscription/claude-opus-4-8")
    assert transports._split_model(pc, None) == "claude-opus-4-8"
    assert transports._split_model(pc, "x/y") == "y"
    assert transports._split_model(pc, "bare") == "bare"


def test_dispatch_returns_none_for_litellm():
    pc = ProviderConfig(name="lm", model="openai/x", transport="litellm")
    assert transports.dispatch(pc, [{"role": "user", "content": "hi"}], None) is None


def test_codex_sse_accumulates_deltas():
    lines = [
        b'event: response.created',
        b'data: {"type":"response.created"}',
        b'data: {"type":"response.output_text.delta","delta":"o"}',
        b'data: {"type":"response.output_text.delta","delta":"i"}',
        b'data: {"type":"response.completed","response":{"output":[]}}',
        b'data: [DONE]',
    ]
    assert transports._codex_sse_text(lines) == "oi"


def test_codex_sse_falls_back_to_completed_output():
    lines = [
        'data: {"type":"response.completed","response":{"output":'
        '[{"content":[{"type":"output_text","text":"oi"}]}]}}',
    ]
    assert transports._codex_sse_text(lines) == "oi"


def test_codex_sse_raises_on_failure_event():
    import pytest
    lines = ['data: {"type":"response.failed","response":{"error":{"message":"x"}}}']
    with pytest.raises(RuntimeError):
        transports._codex_sse_text(lines)


def test_codex_oauth_complete_sends_cloudflare_bypass_headers(monkeypatch):
    """Retrofit anti-403 Cloudflare (VPS): o transport de chat do codex_oauth precisa dos MESMOS
    headers (originator/User-Agent/ChatGPT-Account-Id) que a Responses API do image_gen — sem eles,
    chatgpt.com/backend-api/codex derruba requests de VPS com 403 cf-mitigated mesmo com token válido."""
    from okami.llm import oauth

    monkeypatch.setattr(oauth, "codex_access_token", lambda: "tok-123")
    monkeypatch.setattr(oauth, "codex_account_id", lambda: "acct-77")

    class FakeResp:
        def __enter__(self): return [b'data: {"type":"response.output_text.delta","delta":"oi"}',
                                     b'data: {"type":"response.completed","response":{}}']
        def __exit__(self, *a): return False

    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["headers"] = dict(req.header_items())
        captured["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr(transports.urllib.request, "urlopen", fake_urlopen)
    pc = ProviderConfig(name="codex", model="x", transport="codex_oauth")
    result = transports.codex_oauth_complete(pc, [{"role": "user", "content": "oi"}], None)

    assert result.text == "oi"
    assert captured["url"] == transports.CODEX_URL
    headers = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers["originator"] == "codex_cli_rs"
    assert headers["user-agent"].startswith("codex_cli_rs/")
    assert headers["chatgpt-account-id"] == "acct-77"
    assert headers["authorization"] == "Bearer tok-123"


def test_kwargs_includes_reasoning_effort_and_call_override_wins():
    from okami.llm import providers
    pc = ProviderConfig(name="codex", model="x", reasoning_effort="high")
    kw = providers._kwargs(pc, [], stream=False, model=None)
    assert kw["reasoning_effort"] == "high"                 # default do provider (think)
    kw2 = providers._kwargs(pc, [], stream=False, model=None, reasoning_effort="low")
    assert kw2["reasoning_effort"] == "low"                 # override por chamada (/think) vence


def test_dispatch_threads_reasoning_effort_to_codex(monkeypatch):
    captured = {}

    def fake_codex(pc, messages, model, overrides=None):
        captured["effort"] = (overrides or {}).get("reasoning_effort") or pc.reasoning_effort
        return "ok"

    monkeypatch.setattr(transports, "codex_oauth_complete", fake_codex)
    pc = ProviderConfig(name="codex", model="x", transport="codex_oauth", reasoning_effort="high")
    transports.dispatch(pc, [], None, {"reasoning_effort": "minimal"})
    assert captured["effort"] == "minimal"                  # /think override
    transports.dispatch(pc, [], None, None)
    assert captured["effort"] == "high"                     # cai no default do provider
