"""Anthropic-OAuth tier (mas multi-vendor — a regex casa o corpo de qualquer vendor/proxy): um 429 de TIER de
long-context ('extra usage' + 'long context') NÃO se resolve com backoff nem failover — o request é grande
demais p/ a faixa incluída. A alavanca é COMPRIMIR e re-tentar o MESMO provider (não queimar a assinatura no
fallback). Classifica como long_context_tier → mapeia p/ CONTEXT_OVERFLOW → o harness compacta e retenta."""
from __future__ import annotations

from okami.core.errors import FailureKind
from okami.core.errors import classify as classify_failure
from okami.llm.errors import classify


class _exc(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        if status:
            self.status_code = status


def test_long_context_tier_429_is_distinct_reason():
    ce = classify(_exc("Request exceeds the long context window extra usage allowed on your current tier", 429))
    assert ce.reason == "long_context_tier"
    assert ce.compress and not ce.fallback             # comprime + NÃO failover (não queima a assinatura)


def test_long_context_tier_maps_to_context_overflow():
    f = classify_failure(_exc("long context extra usage limit reached for this tier", 429))
    assert f.kind is FailureKind.CONTEXT_OVERFLOW       # harness compacta e retenta (reusa a maquinaria)


def test_plain_rate_limit_unaffected():
    ce = classify(_exc("Rate limit exceeded, please slow down", 429))
    assert ce.reason == "rate_limit"                    # 429 normal NÃO vira long_context_tier


def test_long_context_alone_without_tier_signal_is_overflow_not_tier():
    # "context window" sem sinal de TIER/extra-usage → overflow normal (não o caso de faixa)
    ce = classify(_exc("maximum context length is 8192 tokens", 400))
    assert ce.reason == "context_overflow"
