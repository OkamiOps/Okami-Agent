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
