"""Backoff exponencial com jitter (porta do retry_utils do Hermes).

Sem isto, o retry roda em loop apertado e martela o rate-limit (thundering herd) — piora o 429.
`base * 2**(attempt-1)`, teto `max_delay`, mais um jitter aleatório p/ descorrelacionar chamadas
concorrentes (gateway roda scheduler + sessões + grupos compartilhando as mesmas chaves).
"""

from __future__ import annotations

import random


def jittered_backoff(attempt: int, *, base_delay: float = 5.0, max_delay: float = 120.0,
                     jitter_ratio: float = 0.5, rand=None) -> float:
    """Segundos a esperar antes da tentativa `attempt` (1-based). `rand` injetável p/ teste. Defaults
    5s/120s (Hermes retry_utils): 2s/60s era cedo demais p/ 429 de quota (janela ~1-2min) — as 3 tentativas
    se gastavam antes do reset e iam direto pro fallback à toa."""
    delay = min(base_delay * (2 ** max(0, attempt - 1)), max_delay)
    r = (rand or random.random)()
    return delay + r * jitter_ratio * delay


def retry_delay(attempt: int, retry_after, *, max_delay: float = 120.0, rand=None) -> float:
    """Quanto esperar antes de re-tentar: se o PROVIDER pediu um tempo (`retry_after`, do header/mensagem),
    HONRA esse valor (capado em `max_delay` p/ não pendurar o turno por 'espere 1h'); senão, backoff
    exponencial com jitter. Honrar o retry_after recupera 429 de quota muito melhor que adivinhar."""
    try:
        ra = float(retry_after) if retry_after else 0.0
    except (TypeError, ValueError):
        ra = 0.0
    if ra > 0:
        return min(ra, max_delay)
    return jittered_backoff(attempt, rand=rand)
