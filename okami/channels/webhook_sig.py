"""Verificadores de assinatura HMAC p/ webhooks (item 14) — funções PURAS, fail-closed.

Sem dep externa: só hmac/hashlib da stdlib. Cada verificador recebe (secret, headers, body bytes)
e devolve bool. Qualquer dúvida (header ausente, formato torto, mismatch) → False (fail-closed):
o webhook só roda algo se a assinatura BATE. Comparação sempre por `hmac.compare_digest`
(constant-time, não vaza tempo).
"""

from __future__ import annotations

import hashlib
import hmac
import time


def _digest(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _secret_ok(secret: str) -> bool:
    """Segredo PRESENTE e não-vazio. Segredo vazio = chave conhecida (b'') → atacante forja a
    assinatura sozinho: por isso secret vazio/ausente é fail-CLOSED (nunca autentica)."""
    return bool((secret or "").strip())


def _eq(got: str, expected: str) -> bool:
    """compare_digest constant-time, à prova de header hostil: assinatura com byte não-ASCII faria
    o compare_digest de str levantar TypeError (DoS no handler não-autenticado) → tratamos como False."""
    try:
        return hmac.compare_digest(got, expected)
    except (TypeError, ValueError):
        return False


def _header(headers, name: str) -> str:
    """Lê um header case-insensitive (dict do http.server vem com casing variado)."""
    if not headers:
        return ""
    target = name.lower()
    for k, v in headers.items():
        if str(k).lower() == target:
            return str(v or "")
    return ""


def verify_github(secret: str, headers, body: bytes) -> bool:
    """GitHub: `X-Hub-Signature-256: sha256=<hmac_sha256(secret, body)>`."""
    if not _secret_ok(secret):
        return False                                    # secret ausente/vazio → fail-closed
    got = _header(headers, "X-Hub-Signature-256")
    if not got or not got.startswith("sha256="):
        return False
    expected = "sha256=" + _digest(secret, body)
    return _eq(got, expected)


def verify_stripe(secret: str, headers, body: bytes, *, tolerance: int = 300) -> bool:
    """Stripe: `Stripe-Signature: t=<ts>,v1=<hmac>`; assinatura é sobre `<ts>.<body>`.

    `tolerance` (segundos): rejeita timestamp velho/futuro demais (anti-replay). Default 300s,
    como o SDK oficial. Aceita múltiplos `v1=` (rotação de segredo): basta um bater.
    """
    if not _secret_ok(secret):
        return False                                    # secret ausente/vazio → fail-closed
    raw = _header(headers, "Stripe-Signature")
    if not raw:
        return False
    ts = ""
    sigs: list[str] = []
    for part in raw.split(","):
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        k, v = k.strip(), v.strip()
        if k == "t":
            ts = v
        elif k == "v1":
            sigs.append(v)
    if not ts or not sigs:
        return False
    try:
        ts_int = int(ts)
    except ValueError:
        return False
    if tolerance and abs(time.time() - ts_int) > tolerance:
        return False                                    # fora da janela → replay, fail-closed
    signed = f"{ts}.".encode("utf-8") + body
    expected = _digest(secret, signed)
    return any(_eq(s, expected) for s in sigs)


def verify_generic(secret: str, headers, body: bytes, *, header: str = "X-Signature") -> bool:
    """Genérico: header configurável com `hmac_sha256(secret, body)` em hex puro."""
    if not _secret_ok(secret):
        return False                                    # secret ausente/vazio → fail-closed
    got = _header(headers, header)
    if not got:
        return False
    # tolera prefixo "sha256=" caso o emissor use esse formato
    if got.startswith("sha256="):
        got = got[len("sha256="):]
    return _eq(got, _digest(secret, body))


# provider → verificador. Genérico precisa do nome do header → wrap no dispatch.
_VERIFIERS = {
    "github": verify_github,
    "stripe": verify_stripe,
}


def verify_hmac(provider: str, secret: str, headers, body: bytes,
                *, header: str = "X-Signature", tolerance: int = 300) -> bool:
    """Despacha p/ o verificador do `provider`. Provider desconhecido → False (fail-closed)."""
    p = (provider or "").lower()
    if p == "github":
        return verify_github(secret, headers, body)
    if p == "stripe":
        return verify_stripe(secret, headers, body, tolerance=tolerance)
    if p == "generic":
        return verify_generic(secret, headers, body, header=header)
    return False
