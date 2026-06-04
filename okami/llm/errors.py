"""Classificação de erros de provider → qual alavanca puxar (porta enxuta do error_classifier do Hermes).

Sem isto, o `complete_messages` rotaciona a chave em QUALQUER erro — inclusive um 400/content-policy
que vai falhar igual em toda chave, queimando o pool e o failover à toa. Aqui a gente decide:
- 429 (rate_limit)  → rotaciona chave do mesmo provider + pode failover; retriável.
- 503/529 (overloaded) → NÃO rotaciona (todas as chaves veem o mesmo provider sobrecarregado);
  back off e troca de provider; retriável.
- 401 (auth transitório) → rotaciona chave; retriável.
- 403 (auth permanente), content-policy, 404 (modelo inexistente) → NÃO retriável; só failover.
- contexto estourado / 413 → comprime e tenta de novo.
- 400 (bad request) → falha rápido (determinístico).
- timeout / 5xx → retriável.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ClassifiedError:
    reason: str
    status: int | None = None
    retryable: bool = True
    rotate_key: bool = False      # tenta outra chave do MESMO provider
    fallback: bool = False        # troca de provider
    compress: bool = False        # contexto estourou → compacta e retenta


def _status_of(exc) -> int | None:
    for attr in ("status_code", "status", "code", "http_status"):
        v = getattr(exc, attr, None)
        if isinstance(v, int) and 100 <= v < 600:
            return v
    m = re.search(r"\b([45]\d\d)\b", str(exc))
    return int(m.group(1)) if m else None


_RATE = re.compile(r"rate.?limit|too many requests|\b429\b|quota", re.I)
_OVERLOAD = re.compile(r"overloaded|\b529\b|\b503\b|temporarily unavailable|capacity", re.I)
_AUTH = re.compile(r"\b401\b|unauthorized|invalid api key|authentication", re.I)
_AUTHPERM = re.compile(r"\b403\b|forbidden|permission denied|account.*(disabled|revoked)", re.I)
_CTX = re.compile(r"context length|maximum context|context window|too long|\b413\b|payload too large", re.I)
_POLICY = re.compile(r"content.?policy|content.?filter|safety|moderation|refus", re.I)
_NOTFOUND = re.compile(r"\b404\b|not found|model.*(does not exist|unavailable|invalid)", re.I)
_TIMEOUT = re.compile(r"timeout|timed out|deadline|read timed", re.I)


def classify(exc) -> ClassifiedError:
    """Mapeia uma exceção (status code e/ou mensagem) numa decisão acionável."""
    s = _status_of(exc)
    msg = str(exc)
    if s == 429 or _RATE.search(msg):
        return ClassifiedError("rate_limit", s, retryable=True, rotate_key=True, fallback=True)
    if s in (503, 529) or _OVERLOAD.search(msg):
        return ClassifiedError("overloaded", s, retryable=True, rotate_key=False, fallback=True)
    if s == 413 or _CTX.search(msg):
        return ClassifiedError("context_overflow", s, retryable=True, compress=True)
    if _POLICY.search(msg):
        return ClassifiedError("content_policy", s, retryable=False, fallback=True)
    if s == 401 or _AUTH.search(msg):
        return ClassifiedError("auth", s, retryable=True, rotate_key=True, fallback=True)
    if s == 403 or _AUTHPERM.search(msg):
        return ClassifiedError("auth_permanent", s, retryable=False, fallback=True)
    if s == 404 or _NOTFOUND.search(msg):
        return ClassifiedError("not_found", s, retryable=False, fallback=True)
    if _TIMEOUT.search(msg):
        return ClassifiedError("timeout", s, retryable=True)
    if s == 400:
        return ClassifiedError("bad_request", s, retryable=False)
    if s is not None and s >= 500:
        return ClassifiedError("server_error", s, retryable=True, fallback=True)
    return ClassifiedError("unknown", s, retryable=True)
