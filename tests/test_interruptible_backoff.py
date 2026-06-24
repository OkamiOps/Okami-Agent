"""Paridade Hermes (multi-vendor): backoff de retry INTERRUPTÍVEL. Um backoff de rate-limit/overloaded
acontece em TODO provider; sem fatiar o sleep + checar cancel, o /stop do dono esperava o sleep INTEIRO
(até 60s) antes de responder."""
from __future__ import annotations

from okami.llm.providers import _interruptible_sleep


def test_sleeps_full_without_cancel():
    slept = []
    r = _interruptible_sleep(1.0, None, _sleep=slept.append)
    assert r is False
    assert abs(sum(slept) - 1.0) < 0.3                  # dormiu ~total


def test_cancels_early():
    slept = []
    n = {"c": 0}

    def cancel():
        n["c"] += 1
        return n["c"] >= 2                              # cancela na 2ª checagem

    r = _interruptible_sleep(30.0, cancel, _sleep=slept.append)
    assert r is True
    assert sum(slept) < 1.0                             # parou cedo (não dormiu 30s)


def test_zero_total_checks_cancel():
    assert _interruptible_sleep(0, lambda: True) is True
    assert _interruptible_sleep(0, lambda: False) is False


def test_heartbeat_fires_during_long_backoff():
    beats = []
    slept = []
    _interruptible_sleep(70.0, cancel=None, on_heartbeat=lambda: beats.append(1), _sleep=slept.append)
    assert len(beats) >= 2                              # ~70s / 30s → ao menos 2 batidas
    assert abs(sum(slept) - 70.0) < 1.0                # dormiu ~total


def test_heartbeat_not_fired_on_short_sleep():
    beats = []
    _interruptible_sleep(5.0, cancel=None, on_heartbeat=lambda: beats.append(1), _sleep=lambda s: None)
    assert beats == []                                 # < 30s → nenhuma batida


def test_heartbeat_error_does_not_break():
    def boom():
        raise RuntimeError("x")
    # heartbeat que explode é best-effort → não derruba o sleep
    _interruptible_sleep(40.0, cancel=None, on_heartbeat=boom, _sleep=lambda s: None)
