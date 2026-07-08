"""Keystone (Fase A): normalização de tokens, custo (modo assinatura), acumulação por sessão."""

from __future__ import annotations

from decimal import Decimal

from okami.llm.usage import (
    CanonicalUsage, Completion, as_completion, cache_hit_ratio, estimate_cost,
    format_tokens, normalize_usage, summarize_store,
)


def test_normalize_codex_subtracts_cache_from_total():
    raw = {"input_tokens": 100, "output_tokens": 20,
           "input_tokens_details": {"cached_tokens": 30},
           "output_tokens_details": {"reasoning_tokens": 5}}
    u = normalize_usage(raw, transport="codex_oauth")
    assert u.input_tokens == 70 and u.cache_read_tokens == 30      # total INCLUI cache → subtraído
    assert u.output_tokens == 20 and u.reasoning_tokens == 5
    assert u.prompt_tokens == 100 and u.total_tokens == 120


def test_normalize_openai_litellm_shape():
    raw = {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 30}}
    u = normalize_usage(raw, transport="litellm")
    assert u.input_tokens == 70 and u.cache_read_tokens == 30 and u.output_tokens == 20


def test_normalize_anthropic_buckets_already_separated():
    raw = {"input_tokens": 50, "output_tokens": 10,
           "cache_read_input_tokens": 40, "cache_creation_input_tokens": 5}
    u = normalize_usage(raw, transport="claude_cli")
    assert u.input_tokens == 50 and u.cache_read_tokens == 40 and u.cache_write_tokens == 5


def test_normalize_none_is_one_request_zero_tokens():
    u = normalize_usage(None, transport="codex_oauth")
    assert u.total_tokens == 0 and u.requests == 1


def test_normalize_gemini_subtracts_cache_and_counts_thinking_tokens():
    """usageMetadata REAL do Gemini: promptTokenCount JÁ INCLUI cachedContentTokenCount (subtrair, como
    o codex) e thoughtsTokenCount (thinking do 2.5+) é ADITIVO — sem somar, o total_tokens subcontava
    silenciosamente todo turno com raciocínio."""
    raw = {"usageMetadata": {"promptTokenCount": 120, "cachedContentTokenCount": 20,
                             "candidatesTokenCount": 15, "thoughtsTokenCount": 40,
                             "totalTokenCount": 175}}
    u = normalize_usage(raw, transport="gemini_native")
    assert u.input_tokens == 100 and u.cache_read_tokens == 20
    assert u.output_tokens == 55 and u.reasoning_tokens == 40   # 15 resposta + 40 thinking
    assert u.prompt_tokens == 120 and u.total_tokens == 175


def test_normalize_bedrock_captures_prompt_cache_buckets():
    """Bedrock Converse com prompt caching ativo (Claude on Bedrock): cacheRead/WriteInputTokens vinham
    p/ lugar nenhum → cache invisível no dashboard (mostrava só inputTokens fresco)."""
    raw = {"inputTokens": 30, "outputTokens": 10, "cacheReadInputTokens": 200, "cacheWriteInputTokens": 5}
    u = normalize_usage(raw, transport="bedrock_native")
    assert u.input_tokens == 30 and u.cache_read_tokens == 200 and u.cache_write_tokens == 5
    assert u.prompt_tokens == 235


def test_cost_subscription_is_included_never_a_dollar():
    u = CanonicalUsage(input_tokens=1_000_000, output_tokens=500_000)
    for tr in ("codex_oauth", "claude_cli"):
        c = estimate_cost(u, transport=tr, provider="codex", model="x")
        assert c.status == "included" and c.amount_usd == Decimal(0) and "$" not in c.label


def test_cost_paypertoken_estimated_and_unknown():
    u = CanonicalUsage(input_tokens=1_000_000, output_tokens=0)
    c = estimate_cost(u, transport="minimax_oauth", provider="minimax", model="openai/MiniMax-M3")
    assert c.status == "estimated" and c.amount_usd == Decimal("0.30")
    c2 = estimate_cost(u, transport="litellm", provider="desconhecido", model="x")
    assert c2.status == "unknown" and c2.amount_usd is None


def test_canonical_usage_add_and_roundtrip():
    a = CanonicalUsage(input_tokens=10, output_tokens=2, cache_read_tokens=3)
    b = CanonicalUsage(input_tokens=5, output_tokens=1)
    s = a + b
    assert s.input_tokens == 15 and s.output_tokens == 3 and s.cache_read_tokens == 3
    assert CanonicalUsage.from_dict(s.to_dict()) == s


def test_as_completion_tolerates_str():
    c = as_completion("oi")
    assert isinstance(c, Completion) and c.text == "oi"
    assert as_completion(c) is c


def test_format_tokens_compact():
    assert format_tokens(950) == "950"
    assert format_tokens(1500) == "1.5K"
    assert format_tokens(3_400_000) == "3.4M"


def test_summarize_store_and_cache_ratio():
    store = {"a": {"usage": {"input": 100, "output": 20, "cache_read": 300}},
             "b": {"usage": {"input": 50, "output": 10}}}
    u = summarize_store(store)
    assert u.input_tokens == 150 and u.output_tokens == 30 and u.cache_read_tokens == 300
    assert round(cache_hit_ratio(u), 2) == round(300 / 450, 2)


def test_store_add_usage_accumulates(tmp_path):
    from okami.gateway.sessions import TranscriptStore
    st = TranscriptStore(tmp_path)
    st.add_usage("7", {"input": 100, "output": 20}, served_by="codex/gpt-5.5")
    st.add_usage("7", {"input": 50, "output": 5})
    e = st.entry("7")
    assert e["usage"] == {"input": 150, "output": 25} and e["served_by"] == "codex/gpt-5.5"
