"""Item 3 da revisão de harness: TETO GLOBAL de tempo da geração. Pior caso atual: len(key_pool)×150s +
fallback recursivo de N providers ≈ cascata de minutos pendurando o canal. O teto aborta a cascata com
TimeoutError (que o loop classifica → encolhe+retry → salvage). Default 300s; OKAMI_OVERALL_TIMEOUT/cfg."""
from __future__ import annotations

import math
import threading

import pytest


def test_run_with_deadline_returns_fast_result():
    from okami.runner import _run_with_deadline
    assert _run_with_deadline(lambda: "ok", 5) == "ok"


def test_run_with_deadline_no_timeout_just_calls():
    from okami.runner import _run_with_deadline
    assert _run_with_deadline(lambda: 42, 0) == 42          # 0/None → sem cronômetro, chama direto


def test_run_with_deadline_raises_on_overrun():
    from okami.runner import _run_with_deadline
    started = threading.Event()
    release = threading.Event()

    def blocked():
        started.set()
        release.wait(1)

    try:
        with pytest.raises(TimeoutError):
            _run_with_deadline(blocked, 0.05)                # estoura o teto → TimeoutError
    finally:
        release.set()
    assert started.is_set()


def test_run_with_deadline_propagates_inner_error():
    from okami.runner import _run_with_deadline

    def boom():
        raise ValueError("erro interno")
    with pytest.raises(ValueError):
        _run_with_deadline(boom, 5)


def test_overall_timeout_default_300():
    from types import SimpleNamespace

    from okami.runner import _overall_timeout_for
    assert _overall_timeout_for(SimpleNamespace(harness={})) == 300.0


def test_overall_timeout_from_cfg():
    from types import SimpleNamespace

    from okami.runner import _overall_timeout_for
    assert _overall_timeout_for(SimpleNamespace(harness={"overall_timeout": 120})) == 120.0


def test_overall_timeout_env_overrides(monkeypatch):
    from types import SimpleNamespace

    from okami.runner import _overall_timeout_for
    monkeypatch.setenv("OKAMI_OVERALL_TIMEOUT", "90")
    assert _overall_timeout_for(SimpleNamespace(harness={"overall_timeout": 999})) == 90.0


@pytest.mark.parametrize("value", [0, -1, math.nan, math.inf, "nope"])
def test_request_bounded_transport_timeout_is_strictly_positive(value):
    from okami.llm.providers import _bounded_request_overrides
    from okami.llm.request import RequestContext, RequestTimeouts

    ctx = RequestContext(RequestTimeouts(total_s=10))
    with pytest.raises(ValueError):
        _bounded_request_overrides(ctx, {"timeout": value})


def test_expired_request_budget_raises_instead_of_passing_zero_timeout():
    from okami.llm.providers import _bounded_request_overrides
    from okami.llm.request import RequestContext, RequestTimeouts, RequestWatchdogTimeout

    now = [100.0]
    ctx = RequestContext(RequestTimeouts(total_s=1), clock=lambda: now[0])
    now[0] = 101.0
    with pytest.raises(RequestWatchdogTimeout, match="total"):
        _bounded_request_overrides(ctx, {})
