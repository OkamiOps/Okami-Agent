"""Pool de credenciais PERSISTENTE (pesquisa #6 item 20, porta do credential_pool do Hermes).

Estado de cada chave por provider (ok/exhausted/dead) com TTL por CLASSE de erro, persistido em
`<okami_home>/cred_pool.json` — sobrevive a restart e é compartilhado entre processos (gateway/cron/
CLI), como o rate_guard cross-sessão. SEGURANÇA: guarda só o FINGERPRINT sha256 da chave, nunca o
valor (fail-closed no limite do disco). FAIL-OPEN: arquivo corrompido/ausente → todas disponíveis.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

# TTL (segundos) por classe de erro. dead = precisa de humano (auth permanente/conta) → segura 24h.
_TTL = {"rate_limit": 3600.0, "overloaded": 60.0, "billing": 6 * 3600.0,
        "auth": 300.0, "auth_permanent": 24 * 3600.0, "account_suspended": 24 * 3600.0,
        "region_blocked": 24 * 3600.0, "default": 3600.0}
_DEAD_REASONS = {"auth_permanent", "account_suspended", "region_blocked"}


def _fingerprint(key: str) -> str:
    return hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:16]


def _path():
    from okami.home import okami_home
    return okami_home() / "cred_pool.json"


def _load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, p)                            # atômico (leitor nunca vê meia-escrita)
    except OSError:
        pass


def mark(provider: str, key: str, reason: str, *, now: float | None = None) -> None:
    """Marca a chave como indisponível pela classe de erro `reason` (TTL correspondente)."""
    now = time.time() if now is None else now
    ttl = _TTL.get(reason, _TTL["default"])
    status = "dead" if reason in _DEAD_REASONS else "exhausted"
    data = _load()
    data.setdefault(provider, {})[_fingerprint(key)] = {
        "status": status, "until": now + ttl, "reason": reason}
    _save(data)


def clear(provider: str, key: str) -> None:
    """Chave voltou a responder → remove a marca (status ok)."""
    data = _load()
    prov = data.get(provider) or {}
    if prov.pop(_fingerprint(key), None) is not None:
        _save(data)


def status(provider: str, key: str, *, now: float | None = None) -> str:
    """'ok' | 'exhausted' | 'dead'. Marca vencida (until ≤ now) conta como 'ok'."""
    now = time.time() if now is None else now
    rec = (_load().get(provider) or {}).get(_fingerprint(key))
    if not rec or rec.get("until", 0) <= now:
        return "ok"
    return rec.get("status", "exhausted")


def available(provider: str, keys: list[str], *, now: float | None = None) -> list[str]:
    """Chaves ESTRITAMENTE utilizáveis (status ok) — pode ser []. O caller decide a degradação
    'todas fora → tenta mesmo assim' (o _available_pool do provider já faz `or pool_cheio`)."""
    now = time.time() if now is None else now
    pool = _load().get(provider) or {}
    out = []
    for k in keys:
        rec = pool.get(_fingerprint(k))
        if not rec or rec.get("until", 0) <= now:
            out.append(k)
    return out


def usable_or_all(provider: str, keys: list[str], *, now: float | None = None) -> list[str]:
    """available() com degradação graciosa: se NENHUMA chave está utilizável, devolve o pool cheio
    (não trava o agente). É o que o provider consome."""
    return available(provider, keys, now=now) or list(keys)
