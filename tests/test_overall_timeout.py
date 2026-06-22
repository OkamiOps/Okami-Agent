"""Item 3 da revisão de harness: TETO GLOBAL de tempo da geração. Pior caso atual: len(key_pool)×150s +
fallback recursivo de N providers ≈ cascata de minutos pendurando o canal. O teto aborta a cascata com
TimeoutError (que o loop classifica → encolhe+retry → salvage). Default 300s; OKAMI_OVERALL_TIMEOUT/cfg."""
from __future__ import annotations

import time

import pytest


def test_run_with_deadline_returns_fast_result():
    from okami.runner import _run_with_deadline
    assert _run_with_deadline(lambda: "ok", 5) == "ok"


def test_run_with_deadline_no_timeout_just_calls():
    from okami.runner import _run_with_deadline
    assert _run_with_deadline(lambda: 42, 0) == 42          # 0/None → sem cronômetro, chama direto


def test_run_with_deadline_raises_on_overrun():
    from okami.runner import _run_with_deadline
    with pytest.raises(TimeoutError):
        _run_with_deadline(lambda: time.sleep(5), 0.2)       # estoura o teto → TimeoutError


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
