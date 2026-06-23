"""Paridade Hermes (sweep): casos onde o Okami ABORTAVA e o Hermes RECUPERA.
- cota TRANSITÓRIA (com sinal de reset) != billing permanente → retenta, não pede humano;
- 5xx de VALIDAÇÃO determinística (parâmetro inválido) → não-retriável (não martela forever);
- mensagem real ANINHADA no body do provider (OpenRouter) → classificar pelo motivo de verdade."""
from __future__ import annotations

from okami.llm.errors import classify


class _E(Exception):
    def __init__(self, msg, status=None, body=None):
        super().__init__(msg)
        if status is not None:
            self.status_code = status
        if body is not None:
            self.body = body


# ---------------------------------------------------------------- cota transitória vs billing
def test_transient_quota_is_rate_limit_not_billing():
    c = classify(_E("You exceeded your current quota; requests remaining: 0, try again in 60s"))
    assert c.reason == "rate_limit" and c.retryable and c.rotate_key   # transitório → retenta


def test_periodic_quota_window_is_rate_limit():
    c = classify(_E("Quota exceeded for this minute window; resets in 30s"))
    assert c.reason == "rate_limit"


def test_permanent_billing_stays_billing():
    c = classify(_E("Your credit balance is too low. Purchase more credits."))
    assert c.reason == "billing"                                       # sem sinal transitório → humano


# ---------------------------------------------------------------- 5xx de validação determinística
def test_validation_500_is_non_retryable():
    c = classify(_E("unknown parameter: 'reasoning_effort'", status=500))
    assert c.reason == "bad_request" and not c.retryable and c.fallback


def test_genuine_500_stays_retryable():
    c = classify(_E("internal server error", status=500))
    assert c.reason == "server_error" and c.retryable


# ---------------------------------------------------------------- motivo aninhado no body
def test_classify_unwraps_nested_provider_body():
    body = {"error": {"metadata": {"raw": '{"error":{"message":"rate limit exceeded, slow down"}}'}}}
    c = classify(_E("litellm.APIError: provider returned an error", body=body))
    assert c.reason == "rate_limit"                                   # achou o motivo real no body
