"""xAI OAuth (SuperGrok/Premium+) — device flow (RFC 8628) + OIDC discovery, portado do Hermes.

O preset antigo em okami.yaml (`oauth.token_url`) tinha um endpoint de token CHUTADO
(`https://auth.x.ai/oauth2/token`) — nunca confirmado nos docs. O Hermes NUNCA chuta esse
valor: ele descobre o `token_endpoint` de verdade via OIDC discovery
(`https://auth.x.ai/.well-known/openid-configuration`) e reusa o valor descoberto tanto
no poll do device flow quanto no refresh. Aqui fazemos o mesmo — o endpoint de token
nunca é hardcoded, sempre vem da descoberta (cacheada em processo).

Duas particularidades do protocolo xAI que fogem do fluxo OAuth "de manual":
  1. expires_at vem do claim `exp` do JWT de acesso (client-side), não do `expires_in`
     do payload — o `expires_in` da xAI é impreciso/ausente em alguns retornos.
  2. xAI ROTACIONA o refresh_token A CADA refresh. Se não salvarmos o refresh_token
     NOVO (write-through), a cadeia morre no próximo refresh (invalid_grant).

Reaproveita save_tokens/load_tokens/_decode_jwt_claims/_post_form/STORE_DIR de
okami.llm.oauth (mesmo store ~/.okami/credentials/<provider>.json, modo 0600).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable

from okami.llm.oauth import (  # noqa: F401  (reexport p/ conveniência/testes)
    STORE_DIR,
    _decode_jwt_claims,
    _post_form,
    load_tokens,
    save_tokens,
)

PROVIDER = "xai-oauth"

XAI_OAUTH_ISSUER = "https://auth.x.ai"
XAI_OAUTH_DISCOVERY_URL = f"{XAI_OAUTH_ISSUER}/.well-known/openid-configuration"
XAI_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
XAI_DEVICE_URL = "https://auth.x.ai/oauth2/device/code"
XAI_SCOPE = "openid profile email offline_access grok-cli:access api:access"
XAI_INFERENCE_BASE = "https://api.x.ai/v1"

# skew "normal" p/ tokens de várias horas (SuperGrok); tokens de device-code (~15min)
# usam um skew bem menor (ver _proactive_skew) senão o token nunca fica "válido".
XAI_REFRESH_SKEW_SECONDS = 3600
_SHORT_LIVED_THRESHOLD = 45 * 60   # abaixo disso o token é "curto" (device-code JWT)
_SHORT_LIVED_SKEW = 120

_DEVICE_PENDING = {"authorization_pending"}
_DEVICE_SLOWDOWN = {"slow_down"}

# cache de descoberta em processo — {"token_endpoint": str, "ts": float}. Nunca hardcoded.
_discovery_cache: dict | None = None
_DISCOVERY_TTL = 24 * 3600


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8"))


def _discover_token_endpoint(now: Callable[[], float] = time.time) -> str:
    """Descobre (e cacheia em processo) o token_endpoint REAL via OIDC discovery.
    Nunca hardcoda o endpoint — o preset antigo chutava e quebrava silenciosamente."""
    global _discovery_cache
    now_ts = now()
    if _discovery_cache and now_ts - _discovery_cache.get("ts", 0) < _DISCOVERY_TTL:
        return _discovery_cache["token_endpoint"]
    doc = _get_json(XAI_OAUTH_DISCOVERY_URL)
    token_endpoint = doc["token_endpoint"]
    _discovery_cache = {"token_endpoint": token_endpoint, "ts": now_ts}
    return token_endpoint


def _normalize(tok: dict, now_ts: float) -> dict:
    """expires_at vem do claim `exp` do JWT (client-side) — não do expires_in do payload."""
    at = tok["access_token"]
    claims = _decode_jwt_claims(at)
    exp = claims.get("exp")
    expires_at = float(exp) if exp else now_ts + int(tok.get("expires_in", 3600))
    return {
        "access_token": at,
        "refresh_token": tok.get("refresh_token"),
        "expires_at": expires_at,
        "raw": tok,
    }


def _proactive_skew(expires_at: float, now_ts: float) -> float:
    """Tokens de device-code duram ~15min: um skew de 1h os deixaria SEMPRE "expirando".
    Só usa o skew cheio (1h) quando sobra bastante vida (tokens de várias horas)."""
    remaining = expires_at - now_ts
    if remaining <= _SHORT_LIVED_THRESHOLD:
        return min(_SHORT_LIVED_SKEW, XAI_REFRESH_SKEW_SECONDS)
    return XAI_REFRESH_SKEW_SECONDS


def _is_expiring(expires_at: float, now_ts: float) -> bool:
    return expires_at <= now_ts + _proactive_skew(expires_at, now_ts)


def xai_login(
    emit: Callable[[str], None],
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Device Authorization Grant (RFC 8628) para xAI. `now`/`sleep` injetáveis p/ teste."""
    dev = _post_form(XAI_DEVICE_URL, {"client_id": XAI_CLIENT_ID, "scope": XAI_SCOPE})
    if "device_code" not in dev:
        raise RuntimeError(f"xai device_authorization falhou: {dev}")

    uri = dev.get("verification_uri_complete") or dev.get("verification_uri", "(ver docs)")
    emit(f"Abra: {uri}\nCódigo: {dev.get('user_code')}\nAguardando autorização...")

    interval = int(dev.get("interval", 5))
    deadline = now() + int(dev.get("expires_in", 900))
    token_endpoint = _discover_token_endpoint(now)

    while now() < deadline:
        sleep(interval)
        tok = _post_form(token_endpoint, {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": XAI_CLIENT_ID,
            "device_code": dev["device_code"],
        })
        if "access_token" in tok:
            data = _normalize(tok, now())
            save_tokens(PROVIDER, data)
            return data
        err = tok.get("error", "")
        if err in _DEVICE_SLOWDOWN:
            interval += 5
            continue
        if err in _DEVICE_PENDING:
            continue
        raise RuntimeError(f"xai device token erro: {tok}")

    raise RuntimeError("xai device login expirou")


def _xai_refresh(refresh_token: str, now: Callable[[], float]) -> dict | None:
    token_endpoint = _discover_token_endpoint(now)
    tok = _post_form(token_endpoint, {
        "grant_type": "refresh_token",
        "client_id": XAI_CLIENT_ID,
        "refresh_token": refresh_token,
    })
    if "access_token" not in tok:
        return None
    new = _normalize(tok, now())
    # xAI ROTACIONA o refresh_token a cada uso — se não salvarmos o novo, a cadeia
    # morre no próximo refresh. Só cai no antigo se a resposta não trouxer um novo.
    new["refresh_token"] = tok.get("refresh_token") or refresh_token
    save_tokens(PROVIDER, new)
    return new


def xai_access_token(now: Callable[[], float] = time.time) -> str | None:
    """Token válido do xAI; refresh proativo com skew adaptativo (ver _proactive_skew)."""
    data = load_tokens(PROVIDER)
    if not data:
        return None
    if not _is_expiring(data.get("expires_at", 0), now()):
        return data.get("access_token")
    refresh = data.get("refresh_token")
    if refresh:
        new = _xai_refresh(refresh, now)
        if new:
            return new["access_token"]
    return data.get("access_token")  # expirado e sem refresh que preste → melhor-esforço


def force_refresh_xai(now: Callable[[], float] = time.time) -> str | None:
    """Força o refresh IGNORANDO expiração (p/ um 401 com token supostamente válido)."""
    data = load_tokens(PROVIDER)
    rt = (data or {}).get("refresh_token")
    if not rt:
        return None
    new = _xai_refresh(rt, now)
    return new["access_token"] if new else None
