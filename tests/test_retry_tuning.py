"""Item 4 da revisão de harness: backoff base 5s/teto 120s (era 2s/60s — cedo demais p/ 429 de quota,
cuja janela costuma ser 1-2min) + HONRAR o retry_after que o provider pede (capado)."""
from __future__ import annotations


def test_jittered_backoff_new_defaults():
    from okami.llm.retry import jittered_backoff
    assert jittered_backoff(1, rand=lambda: 0.0) == 5.0       # base 5 (era 2)
    assert jittered_backoff(2, rand=lambda: 0.0) == 10.0
    assert jittered_backoff(10, rand=lambda: 0.0) == 120.0    # teto 120 (era 60)


def test_retry_delay_honors_retry_after():
    from okami.llm.retry import retry_delay
    assert retry_delay(1, 30) == 30.0                         # provider pediu 30s → honra exatamente
    assert retry_delay(3, 45.0) == 45.0


def test_retry_delay_caps_huge_retry_after():
    from okami.llm.retry import retry_delay
    assert retry_delay(1, 9999) == 120.0                      # 'espere 1h' → não pendura o turno; cap no max


def test_retry_delay_falls_back_to_backoff_without_retry_after():
    from okami.llm.retry import retry_delay
    assert retry_delay(1, None, rand=lambda: 0.0) == 5.0      # sem retry_after → backoff (novo default)
    assert retry_delay(1, 0, rand=lambda: 0.0) == 5.0         # 0/negativo → backoff
