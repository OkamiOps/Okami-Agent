"""Tier 1 (#9): sanitiza envelope CRU de erro de provider antes de chegar ao chat (Telegram/etc.).

O redact já mascara segredo; este filtro vai além — mapeia "401 {...} x-request-id: req_…" p/ uma
categoria curta e segura, sem vazar HTTP body / request-id / fragmento de chave / texto interno no
inbox móvel. Prosa normal passa intacta (só age em erro de PROVIDER, em turno que FALHOU)."""
from __future__ import annotations


def test_sanitize_maps_401_without_leaking():
    from okami.gateway.response_filters import sanitize_provider_error
    raw = ('AuthenticationError: 401 {"type":"error","error":{"message":"incorrect api key sk-abc123"}} '
           "x-request-id: req_98765")
    out = sanitize_provider_error(raw)
    assert "autentic" in out.lower()
    assert "sk-abc123" not in out and "req_98765" not in out and "401" not in out


def test_sanitize_rate_limit():
    from okami.gateway.response_filters import sanitize_provider_error
    assert "limit" in sanitize_provider_error("Error 429 rate_limit_exceeded for org-xyz").lower()


def test_sanitize_overloaded():
    from okami.gateway.response_filters import sanitize_provider_error
    assert "sobrecarreg" in sanitize_provider_error('{"type":"overloaded_error"} 529').lower()


def test_sanitize_passes_normal_prose():
    from okami.gateway.response_filters import sanitize_provider_error
    txt = "Encontrei o problema no seu código: a função retorna None quando a lista está vazia."
    assert sanitize_provider_error(txt) == txt


def test_sanitize_passes_short_clean_reason():
    from okami.gateway.response_filters import sanitize_provider_error
    assert sanitize_provider_error("orçamento de passos esgotado") == "orçamento de passos esgotado"
