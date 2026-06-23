"""Classificador de erros EXPANDIDO (pesquisa #5 item 54 — ~22 razões do Hermes, as que importam).

Novas razões com a alavanca certa: billing (≠ rate_limit! rotaciona JÁ — outra chave pode ter
crédito), network (transitório, failover), model_retired/region_blocked/account_suspended (não
insiste), empty_response (retry/failover). E a doutrina content_policy → NUNCA re-enviar payload
idêntico (never_repeat consultado pelo retry: sem failover do MESMO conteúdo).
"""
from __future__ import annotations

import pytest

from okami.config import build_config
from okami.llm import providers as prov
from okami.llm.errors import classify


class _exc(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        if status:
            self.status_code = status


# ------------------------------------------------------------------ novas razões
def test_billing_is_not_rate_limit_and_rotates_now():
    # OpenAI manda 429 + insufficient_quota quando é BILLING — tratar como rate_limit só faz backoff
    # à toa; a alavanca certa é rotacionar a chave JÁ (outra chave pode ter crédito) e failover.
    ce = classify(_exc("You exceeded your current quota, please check your plan and billing details.", 429))
    assert ce.reason == "billing"
    assert ce.rotate_key and ce.fallback and ce.retryable


def test_anthropic_low_credit_is_billing():
    ce = classify(_exc("Your credit balance is too low to access the Anthropic API", 400))
    assert ce.reason == "billing"


def test_connection_reset_is_network_transient():
    ce = classify(_exc("Connection reset by peer"))
    assert ce.reason == "network"
    assert ce.retryable and ce.fallback


def test_dns_failure_is_network():
    assert classify(_exc("getaddrinfo failed")).reason == "network"


def test_model_retired_not_retryable():
    ce = classify(_exc("model claude-1 has been decommissioned", 400))
    assert ce.reason == "model_retired"
    assert not ce.retryable and ce.fallback


def test_region_blocked_not_retryable():
    ce = classify(_exc("this model is not available in your region", 403))
    assert ce.reason == "region_blocked"
    assert not ce.retryable and ce.fallback


def test_account_suspended_not_retryable():
    ce = classify(_exc("your account has been suspended", 403))
    assert ce.reason == "account_suspended"
    assert not ce.retryable


def test_empty_response_reason():
    ce = classify(prov.EmptyResponse("resposta vazia do provider"))
    assert ce.reason == "empty_response"
    assert ce.retryable and ce.fallback


def test_content_policy_marks_never_repeat():
    ce = classify(_exc("content_policy violation"))
    assert ce.reason == "content_policy"
    assert ce.never_repeat


def test_plain_429_still_rate_limit():
    assert classify(_exc("too many requests", 429)).reason == "rate_limit"


# ------------------------------------------------------------------ retry consulta as dicas
def test_billing_key_is_parked_and_pool_rotates(monkeypatch, tmp_path):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)   # isola a guarda cross-sessão
    prov._key_cooldown.clear()
    cfg = build_config({"default_provider": "a",
                        "providers": {"a": {"model": "ma", "api_keys": ["k1", "k2"]}}})
    calls = []

    def fake_one(pc, messages, model, schema, overrides):
        calls.append(overrides.get("_api_key"))
        if len(calls) == 1:
            raise _exc("You exceeded your current quota, please check your plan and billing details.", 429)
        return "ok"

    monkeypatch.setattr(prov, "_complete_one", fake_one)
    out = prov.complete_messages(cfg, [{"role": "user", "content": "x"}], _sleep=lambda s: None)
    assert out == "ok"
    assert len(set(calls)) == 2                       # rotacionou JÁ p/ outra chave
    assert calls[0] in prov._key_cooldown             # chave sem crédito parqueada
    prov._key_cooldown.clear()


def test_never_repeat_blocks_identical_fallback(monkeypatch, tmp_path):
    # content_policy: re-enviar o MESMO payload p/ outro provider é repetir igual → não failover aqui
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)   # isola a guarda cross-sessão
    cfg = build_config({"default_provider": "a", "providers": {
        "a": {"model": "ma", "fallback": ["b"]}, "b": {"model": "mb"}}})
    tried = []

    def fake_one(pc, messages, model, schema, overrides):
        tried.append(pc.name)
        raise _exc("content_policy violation", 400)

    monkeypatch.setattr(prov, "_complete_one", fake_one)
    with pytest.raises(Exception):
        prov.complete_messages(cfg, [{"role": "user", "content": "x"}], _sleep=lambda s: None)
    # paridade Hermes (#4): content_policy faz FAILOVER p/ outra família (que talvez não recuse), mas NÃO
    # re-tenta o MESMO provider com o payload idêntico — 'a' aparece só 1x, depois tenta 'b'.
    assert tried == ["a", "b"] and tried.count("a") == 1
