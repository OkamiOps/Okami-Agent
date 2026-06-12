"""Circuit breaker por plataforma (pesquisa #6 item 23, paridade Hermes _failed_platforms).

Canal que falha repetido entra em backoff exponencial (30s→…→cap) — para de martelar uma plataforma
morta (token revogado, API fora). /platform list|pause|resume controla manualmente.
"""
from __future__ import annotations

from okami.gateway.circuit import PlatformBreaker


def test_healthy_polls():
    b = PlatformBreaker()
    assert b.should_poll("telegram", now=0.0)


def test_failure_pauses_with_backoff():
    b = PlatformBreaker(base=30.0, cap=300.0)
    b.record_failure("slack", now=0.0)
    assert not b.should_poll("slack", now=10.0)        # dentro do backoff
    assert b.should_poll("slack", now=31.0)            # passou os 30s


def test_backoff_is_exponential():
    b = PlatformBreaker(base=30.0, cap=300.0)
    assert b.record_failure("x", now=0.0) == 30.0      # 1ª falha → 30s
    assert b.record_failure("x", now=0.0) == 60.0      # 2ª → 60s
    assert b.record_failure("x", now=0.0) == 120.0     # 3ª → 120s


def test_backoff_caps():
    b = PlatformBreaker(base=30.0, cap=120.0)
    for _ in range(10):
        secs = b.record_failure("y", now=0.0)
    assert secs == 120.0                               # teto respeitado


def test_success_resets():
    b = PlatformBreaker()
    b.record_failure("z", now=0.0)
    b.record_failure("z", now=0.0)
    b.record_success("z")
    assert b.should_poll("z", now=0.1)                 # recuperou → volta a pollar
    assert b.record_failure("z", now=0.0) == 30.0      # contador zerou → backoff base de novo


def test_manual_pause_resume():
    b = PlatformBreaker()
    b.pause("discord")
    assert not b.should_poll("discord", now=10_000.0)  # pausa manual não expira sozinha
    b.resume("discord")
    assert b.should_poll("discord", now=0.0)


def test_status_lists_state():
    b = PlatformBreaker()
    b.record_failure("slack", now=0.0)
    b.pause("discord")
    st = {s["name"]: s for s in b.status(now=5.0)}
    assert st["slack"]["state"] == "backoff" and st["slack"]["fails"] == 1
    assert st["discord"]["state"] == "paused"
