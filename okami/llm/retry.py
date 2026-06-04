"""Backoff exponencial com jitter (porta do retry_utils do Hermes).

Sem isto, o retry roda em loop apertado e martela o rate-limit (thundering herd) — piora o 429.
`base * 2**(attempt-1)`, teto `max_delay`, mais um jitter aleatório p/ descorrelacionar chamadas
concorrentes (gateway roda scheduler + sessões + grupos compartilhando as mesmas chaves).
"""

from __future__ import annotations

import random


def jittered_backoff(attempt: int, *, base_delay: float = 2.0, max_delay: float = 60.0,
                     jitter_ratio: float = 0.5, rand=None) -> float:
    """Segundos a esperar antes da tentativa `attempt` (1-based). `rand` injetável p/ teste."""
    delay = min(base_delay * (2 ** max(0, attempt - 1)), max_delay)
    r = (rand or random.random)()
    return delay + r * jitter_ratio * delay
