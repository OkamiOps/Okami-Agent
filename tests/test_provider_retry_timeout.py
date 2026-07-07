"""FIX 3 (max_retries) + FIX 4 (timeout por tier), diagnosticados junto com o bug do probe nativo.

FIX 3: `attempts = max(1, len(pc.key_pool()))` prendia o nº de retries ao tamanho do pool de chaves —
um provider de UMA chave só (sem pool) tomava ZERO retry num erro transiente (429/503/timeout) e caía
pro fallback antes de dar uma segunda chance. `max_retries` (default 3) vira o PISO das tentativas.

FIX 4: timeout FIXO de 150s (depois 600s por engano de leitura — na verdade era só uma constante única)
penalizava TODO provider igual, sem respeitar que LOCAL (LMStudio/Ollama) é sabidamente mais lento que
nuvem. `timeout_seconds` explícito > default por tier (local=1800s, resto=600s)."""
from __future__ import annotations

import pytest

import okami.llm.providers as prov
from okami.config import ProviderConfig, build_config


def _exc(msg, status=None):
    e = RuntimeError(msg)
    if status is not None:
        e.status_code = status
    return e


# ----------------------------------------------------------------- FIX 3: max_retries é o piso
def test_max_retries_default_is_three():
    pc = ProviderConfig(name="p", model="m")
    assert pc.max_retries == 3


def test_single_key_provider_retries_transient_error_instead_of_failing_immediately(monkeypatch):
    cfg = build_config({"default_provider": "a", "providers": {"a": {"model": "ma"}}})   # sem pool (0 chaves)
    calls = []

    def fake_one(pc, messages, model, schema, overrides):
        calls.append(pc.name)
        if len(calls) < 3:
            raise _exc("Too Many Requests", 429)          # rate_limit: retryable
        return "ok-terceira"

    monkeypatch.setattr(prov, "_complete_one", fake_one)
    out = prov.complete_messages(cfg, [{"role": "user", "content": "x"}], _sleep=lambda s: None)
    assert out == "ok-terceira"
    assert len(calls) == 3                                 # 2 falhas + 1 sucesso — SEM max_retries, seria 1 tentativa só


def test_single_key_provider_without_retry_would_have_failed_before_fix():
    # documenta o bug: attempts = max(1, len(pool)) com pool VAZIO dava attempts=1 (regressão coberta
    # pelo teste acima que agora exige 3 tentativas via max_retries).
    pc = ProviderConfig(name="a", model="ma")
    assert pc.key_pool() == []
    assert max(1, len(pc.key_pool())) == 1                 # comportamento ANTIGO (sem a fix)
    assert max(pc.max_retries, len(pc.key_pool())) == 3     # comportamento NOVO (com a fix)


def test_max_retries_configurable_and_key_pool_still_wins_when_larger():
    pc = ProviderConfig(name="a", model="ma", api_keys=["k1", "k2", "k3", "k4", "k5"], max_retries=2)
    assert max(pc.max_retries, len(pc.key_pool())) == 5     # pool maior que o piso ainda manda (giro de chave)


# ----------------------------------------------------------------- FIX 4: timeout por tier
def test_resolve_timeout_explicit_wins():
    pc = ProviderConfig(name="p", model="m", tier="local", timeout_seconds=42.0)
    assert prov.resolve_timeout(pc) == 42.0


def test_resolve_timeout_local_tier_default_is_generous():
    pc = ProviderConfig(name="p", model="m", tier="local")
    assert prov.resolve_timeout(pc) == 1800.0


@pytest.mark.parametrize("tier", ["strong", "weak", "unknown", ""])
def test_resolve_timeout_cloud_tiers_default_shorter(tier):
    pc = ProviderConfig(name="p", model="m", tier=tier)
    assert prov.resolve_timeout(pc) == 600.0


def test_kwargs_uses_resolved_timeout_for_local_tier():
    pc = ProviderConfig(name="p", model="openai/x", tier="local")
    kw = prov._kwargs(pc, [{"role": "user", "content": "oi"}], stream=False, model=None)
    assert kw["timeout"] == 1800.0


def test_kwargs_respects_explicit_timeout_override_via_config():
    pc = ProviderConfig(name="p", model="openai/x", tier="local", timeout_seconds=99.0)
    kw = prov._kwargs(pc, [{"role": "user", "content": "oi"}], stream=False, model=None)
    assert kw["timeout"] == 99.0


def test_kwargs_per_call_override_still_wins_over_tier_default():
    pc = ProviderConfig(name="p", model="openai/x", tier="strong")
    kw = prov._kwargs(pc, [{"role": "user", "content": "oi"}], stream=False, model=None, timeout=5.0)
    assert kw["timeout"] == 5.0
