"""Guarda de rate-limit CROSS-SESSÃO (porta do nous_rate_guard.py do Hermes).

A dor: gateway, cron e CLI são PROCESSOS separados compartilhando o mesmo provider. Um 429
num deles não impedia os outros de martelar — cada turno re-tenta ~3×, então um único limite
virava 9+ chamadas extras contra a MESMA quota (amplificação de retry). Aqui o primeiro
429/529 grava o horário de reset em ~/.okami/rate_limits/<provider>.json (escrita atômica) e
toda sessão consulta `blocked_for()` antes de chamar: bloqueado → pula direto pro fallback.

Fail-open por princípio: arquivo corrompido/ausente/erro de IO → 0.0 (a guarda otimiza,
nunca pode travar o agente).
"""
from __future__ import annotations

import json
import os
import re
import time

_TTL_RATE_LIMIT = 3600.0     # 429 sem retry-after: quota por hora é o caso comum
_TTL_OVERLOADED = 45.0       # 503/529 é transitório — segundos, não horas


def _dir():
    from okami.home import okami_home
    return okami_home() / "rate_limits"


def _path(provider: str):
    safe = re.sub(r"[^a-z0-9_-]+", "_", str(provider).lower()) or "default"
    return _dir() / f"{safe}.json"


def _write(provider: str, until: float) -> None:
    try:
        d = _dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = _path(provider).with_suffix(".tmp")
        tmp.write_text(json.dumps({"until": until, "noted_at": time.time()}), encoding="utf-8")
        os.replace(tmp, _path(provider))             # atômico: leitor nunca vê arquivo meia-escrito
    except OSError:
        pass                                          # guarda é best-effort


def note_rate_limited(provider: str, *, ttl: float | None = None,
                      retry_after: float | None = None, genuine: bool | None = None) -> None:
    """Registra um 429. Precedência (bug #9): retry-after do provider > ttl explícito do caller >
    `genuine` (quota da CONTA esgotou → 1h) > default TRANSITÓRIO curto. Sem retry-after e sem sinal
    de exaustão genuína, um 429 num gateway multiplexado é tratado como transitório (upstream sem
    capacidade) — pausa curta anti-stampede, NÃO trava o provider inteiro por 1h."""
    if retry_after and retry_after > 0:
        wait = float(retry_after)                 # o provider disse explicitamente quanto esperar
    elif ttl is not None:
        wait = float(ttl)                          # caller explicitou o ttl → honra
    elif genuine:
        wait = _TTL_RATE_LIMIT                      # quota da conta esgotou de verdade → 1h
    else:
        wait = _TTL_OVERLOADED                      # 429 ambíguo/transitório → pausa curta (anti-1h-lockout)
    _write(provider, time.time() + wait)


def note_overloaded(provider: str, *, ttl: float = _TTL_OVERLOADED) -> None:
    """Registra um 503/529 (transitório): pausa curta p/ TODAS as sessões — sem retry-stampede."""
    _write(provider, time.time() + float(ttl))


def blocked_for(provider: str) -> float:
    """Segundos até o provider liberar (0.0 = livre). Fail-open em qualquer erro."""
    try:
        data = json.loads(_path(provider).read_text(encoding="utf-8"))
        return max(0.0, float(data.get("until", 0)) - time.time())
    except (OSError, ValueError, TypeError):
        return 0.0


def clear(provider: str) -> None:
    """Remove a marca (ex.: chamada voltou a funcionar)."""
    try:
        _path(provider).unlink(missing_ok=True)
    except OSError:
        pass


def is_genuine_rate_limit(status: int) -> bool:
    """#11: distingue limite GENUÍNO de quota (429 → backoff longo/1h) de sobrecarga TRANSIENTE do
    upstream (503/529 → segundos). Só 429 é quota real; 5xx é capacidade momentânea (não some a quota
    do dono). Espelha a distinção que o note_rate_limited/note_overloaded já aplicam nos TTLs."""
    return int(status) == 429
