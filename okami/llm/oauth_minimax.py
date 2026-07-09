"""MiniMax OAuth (Portal) — protocolo REAL, portado do Hermes.

O preset antigo em okami.yaml (`api_base: https://api.minimax.io/v1`, client_id
"CONFIRMAR") era um chute errado. O fluxo real do MiniMax NÃO é RFC 8628
device_code clássico: é um "user_code" próprio deles —
  1. POST {portal}/oauth/code  (PKCE S256 + state)  → devolve user_code/verification_uri
  2. POST {portal}/oauth/token (grant_type=urn:ietf:params:oauth:grant-type:user_code) em loop,
     até status virar "success"/"succeeded" (ou "error"/"failed")
  3. refresh via grant_type=refresh_token no mesmo endpoint

E a base de inferência é o protocolo Anthropic Messages (`{portal}/anthropic`),
NÃO o `/v1` OpenAI-compat que o preset antigo assumia.

Reaproveita save_tokens/load_tokens/_decode_jwt_claims/STORE_DIR de okami.llm.oauth
(mesmo store ~/.okami/credentials/<provider>.json, modo 0600).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Callable

from okami.llm.oauth import STORE_DIR, _decode_jwt_claims, load_tokens, save_tokens  # noqa: F401  (reexport p/ conveniência)

MINIMAX_CLIENT_ID = "78257093-7e40-4613-99e0-527b14b39113"
MINIMAX_SCOPE = "group_id profile model.completion"
MINIMAX_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:user_code"
MINIMAX_PORTAL_GLOBAL = "https://api.minimax.io"
MINIMAX_PORTAL_CN = "https://api.minimaxi.com"
MINIMAX_REFRESH_SKEW = 60          # segundos de folga antes de expirar (tokens duram ~15min)
MINIMAX_MS_EPOCH_THRESHOLD = 10 ** 12   # acima disso só faz sentido como epoch em ms (~ano 2001)

_SUCCESS_STATUSES = {"success", "succeeded"}
_ERROR_STATUSES = {"error", "failed"}


def _portal(region: str = "global") -> str:
    return MINIMAX_PORTAL_CN if region == "cn" else MINIMAX_PORTAL_GLOBAL


def minimax_inference_base(region: str = "global") -> str:
    """Base da API de inferência — protocolo Anthropic Messages (não o /v1 OpenAI-compat)."""
    return f"{_portal(region)}/anthropic"


def _pkce_pair() -> tuple[str, str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    return verifier, challenge, state


def _post_form(url: str, fields: dict, extra_headers: dict | None = None) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        try:
            payload = json.loads(detail)
            if isinstance(payload, dict):
                return payload
        except (ValueError, TypeError):
            pass
        return {"status": "error", "_status": e.code, "_detail": detail[:300]}


def _looks_like_ms_epoch(value: int) -> bool:
    """`expired_in` é AMBÍGUO no protocolo MiniMax: às vezes é um epoch absoluto em
    ms (ex.: 1_770_000_000_000), às vezes é um TTL em segundos (ex.: 900). Um TTL
    plausível nunca passa de alguns milhões; um epoch-ms de hoje está na casa de
    10^12+. O threshold 10^12 corresponde a ~set/2001 em ms — nenhum TTL real chega
    perto disso, então > 10^12 só pode ser epoch."""
    return value > MINIMAX_MS_EPOCH_THRESHOLD


def _resolve_expires_at(expired_in: int, now: float) -> float:
    if _looks_like_ms_epoch(expired_in):
        return expired_in / 1000.0
    return now + max(1, expired_in)


def _normalize(tok: dict, now_ts: float) -> dict:
    expires_at = _resolve_expires_at(int(tok.get("expired_in", 900)), now_ts)
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "expires_at": expires_at,
        "raw": tok,
    }


def minimax_oauth_login(
    emit: Callable[[str], None],
    region: str = "global",
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval: float = 2.0,
) -> dict:
    """Fluxo OAuth "user_code" do MiniMax Portal (PKCE S256). `now`/`sleep` injetáveis p/ teste."""
    portal = _portal(region)
    verifier, challenge, state = _pkce_pair()

    code_resp = _post_form(
        f"{portal}/oauth/code",
        {
            "response_type": "code",
            "client_id": MINIMAX_CLIENT_ID,
            "scope": MINIMAX_SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        },
        extra_headers={"x-request-id": str(uuid.uuid4())},
    )
    if "user_code" not in code_resp:
        raise RuntimeError(f"minimax oauth/code falhou: {code_resp}")

    user_code = code_resp["user_code"]
    verification_uri = code_resp.get("verification_uri", "(ver docs)")
    emit(f"Abra: {verification_uri}\nCódigo: {user_code}\nAguardando autorização...")

    expired_in = int(code_resp.get("expired_in", 600))
    deadline = _resolve_expires_at(expired_in, now())

    while now() < deadline:
        sleep(poll_interval)
        tok = _post_form(
            f"{portal}/oauth/token",
            {
                "grant_type": MINIMAX_GRANT_TYPE,
                "client_id": MINIMAX_CLIENT_ID,
                "user_code": user_code,
                "code_verifier": verifier,
                "state": state,
            },
        )
        status = tok.get("status")
        if status in _SUCCESS_STATUSES and "access_token" in tok:
            data = _normalize(tok, now())
            save_tokens("minimax", data)
            return data
        if status in _ERROR_STATUSES:
            raise RuntimeError(f"minimax oauth/token erro: {tok}")
        # "pending" (ou qualquer status desconhecido) → continua o poll.
        continue

    raise RuntimeError("minimax oauth login expirou")


def _minimax_refresh(refresh_token: str, region: str, now_ts: float) -> dict | None:
    portal = _portal(region)
    tok = _post_form(
        f"{portal}/oauth/token",
        {
            "grant_type": "refresh_token",
            "client_id": MINIMAX_CLIENT_ID,
            "refresh_token": refresh_token,
        },
    )
    status = tok.get("status")
    if status in _ERROR_STATUSES or "access_token" not in tok:
        return None
    new = _normalize(tok, now_ts)
    new["refresh_token"] = new.get("refresh_token") or refresh_token
    save_tokens("minimax", new)
    return new


def minimax_access_token(now: Callable[[], float] = time.time, region: str = "global") -> str | None:
    """Token válido do MiniMax; renova via refresh_token quando perto de expirar
    (skew de 60s — tokens duram ~15min, então essa checagem roda por requisição)."""
    data = load_tokens("minimax")
    if not data:
        return None
    if data.get("expires_at", 0) - MINIMAX_REFRESH_SKEW > now():
        return data.get("access_token")
    refresh = data.get("refresh_token")
    if refresh:
        new = _minimax_refresh(refresh, region, now())
        if new:
            return new["access_token"]
    return data.get("access_token")  # expirado e sem refresh que preste → melhor-esforço


def force_refresh_minimax(now: Callable[[], float] = time.time, region: str = "global") -> str | None:
    """Força o refresh IGNORANDO expiração (p/ um 401 com token supostamente válido)."""
    data = load_tokens("minimax")
    rt = (data or {}).get("refresh_token")
    if not rt:
        return None
    new = _minimax_refresh(rt, region, now())
    return new["access_token"] if new else None
