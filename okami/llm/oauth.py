"""Login OAuth de assinatura — device flow + token store + refresh.

Dois caminhos:
- CLI-delegado (preferido quando há CLI oficial): ex. `codex login --device-auth`.
- Device flow nativo (RFC 8628): para MiniMax e como fallback. POST device_authorization
  → mostra URL+código → poll token → salva access/refresh; refresh automático ao expirar.

Tokens em ~/.okami/credentials/<provider>.json (modo 0600).
ATENÇÃO: client_id/endpoints por provider precisam ser confirmados nos docs antes do uso
ao vivo (marcados CONFIRMAR no okami.yaml). O store/refresh em si é genérico e testável.
"""

from __future__ import annotations

import base64
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

STORE_DIR = Path.home() / ".okami" / "credentials"


def _store_path(provider: str) -> Path:
    return STORE_DIR / f"{provider}.json"


def save_tokens(provider: str, data: dict) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    p = _store_path(provider)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass


def load_tokens(provider: str) -> dict | None:
    p = _store_path(provider)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def has_tokens(provider: str) -> bool:
    return _store_path(provider).exists()


def _normalize(tok: dict, now: float) -> dict:
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "expires_at": now + int(tok.get("expires_in", 3600)),
        "raw": tok,
    }


def _post_form(url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"http_{e.code}", "_detail": e.read().decode("utf-8", "ignore")[:300]}


def device_login(provider: str, oauth: dict, emit: Callable[[str], None],
                 now: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Device Authorization Grant (RFC 8628). `now`/`sleep` injetáveis p/ teste."""
    client_id = oauth["client_id"]
    dev = _post_form(oauth["device_authorization_url"],
                     {"client_id": client_id, "scope": oauth.get("scope", "")})
    if "device_code" not in dev:
        raise RuntimeError(f"device_authorization falhou: {dev}")
    uri = dev.get("verification_uri_complete") or dev.get("verification_uri", "(ver docs)")
    emit(f"Abra: {uri}\nCódigo: {dev.get('user_code')}\nAguardando autorização...")
    interval = int(dev.get("interval", 5))
    deadline = now() + int(dev.get("expires_in", 600))
    while now() < deadline:
        sleep(interval)
        tok = _post_form(oauth["token_url"], {
            "client_id": client_id,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": dev["device_code"],
        })
        if "access_token" in tok:
            data = _normalize(tok, now())
            save_tokens(provider, data)
            return data
        err = tok.get("error", "")
        if err in ("authorization_pending", "slow_down"):
            if err == "slow_down":
                interval += 5
            continue
        raise RuntimeError(f"device token erro: {tok}")
    raise RuntimeError("device login expirou")


def get_valid_token(provider: str, oauth: dict | None, now: Callable[[], float] = time.time) -> str | None:
    """Retorna access_token válido; refaz refresh se expirado e possível."""
    data = load_tokens(provider)
    if not data:
        return None
    if data.get("expires_at", 0) - 60 > now():
        return data.get("access_token")
    refresh = data.get("refresh_token")
    if oauth and refresh:
        tok = _post_form(oauth["token_url"], {
            "client_id": oauth["client_id"],
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        })
        if "access_token" in tok:
            new = _normalize(tok, now())
            new["refresh_token"] = new.get("refresh_token") or refresh
            save_tokens(provider, new)
            return new["access_token"]
    return data.get("access_token")  # expirado, melhor-esforço


def cli_delegate_login(cmd: list[str]) -> int:
    """Delega para um CLI oficial (ex.: codex login --device-auth). Fallback opcional."""
    return subprocess.call(cmd)


# ============================================================================
# Codex / OpenAI — device flow NATIVO (sem depender do codex CLI).
# Valores do client público da OpenAI (auth.openai.com), igual ao Codex CLI/OpenClaw.
# ============================================================================
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_USERCODE_URL = "https://auth.openai.com/api/accounts/deviceauth/usercode"
CODEX_DEVICE_TOKEN_URL = "https://auth.openai.com/api/accounts/deviceauth/token"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_DEVICE_PAGE = "https://auth.openai.com/codex/device"
CODEX_REDIRECT = "https://auth.openai.com/deviceauth/callback"
_CLI_AUTH = Path.home() / ".codex" / "auth.json"


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "okami-agent")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"http_{e.code}", "_detail": e.read().decode("utf-8", "ignore")[:300]}


def codex_device_login(emit: Callable[[str], None],
                       now: Callable[[], float] = time.time,
                       sleep: Callable[[float], None] = time.sleep) -> dict:
    """Device flow nativo da OpenAI (servidor gera o PKCE e devolve no poll)."""
    start = _post_json(CODEX_USERCODE_URL, {"client_id": CODEX_CLIENT_ID})
    device_auth_id = start.get("device_auth_id")
    user_code = start.get("user_code") or start.get("usercode")
    if not device_auth_id or not user_code:
        raise RuntimeError(f"usercode falhou: {start}")
    interval = int(start.get("interval", 5))
    emit(f"Abra: {CODEX_DEVICE_PAGE}\nCódigo: {user_code}\nAguardando autorização...")

    deadline = now() + int(start.get("expires_in", 900))
    auth_code = code_verifier = None
    while now() < deadline:
        sleep(interval)
        poll = _post_json(CODEX_DEVICE_TOKEN_URL,
                          {"device_auth_id": device_auth_id, "user_code": user_code})
        if poll.get("authorization_code"):
            auth_code = poll["authorization_code"]
            code_verifier = poll.get("code_verifier", "")
            break
        if poll.get("error") and poll["error"] not in ("authorization_pending", "slow_down"):
            raise RuntimeError(f"poll erro: {poll}")
    if not auth_code:
        raise RuntimeError("device login expirou sem autorização")

    tok = _post_form(CODEX_OAUTH_TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": CODEX_CLIENT_ID,
        "code": auth_code,
        "code_verifier": code_verifier or "",
        "redirect_uri": CODEX_REDIRECT,
    })
    if "access_token" not in tok:
        raise RuntimeError(f"exchange /oauth/token falhou: {tok}")
    data = _normalize(tok, now())
    save_tokens("codex", data)
    return data


def _codex_refresh(refresh_token: str, now: Callable[[], float]) -> dict | None:
    tok = _post_form(CODEX_OAUTH_TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": CODEX_CLIENT_ID,
        "refresh_token": refresh_token,
    })
    if "access_token" not in tok:
        return None
    new = _normalize(tok, now())
    new["refresh_token"] = new.get("refresh_token") or refresh_token
    save_tokens("codex", new)
    return new


def codex_access_token(now: Callable[[], float] = time.time) -> str | None:
    """Token válido do Codex: nosso store (com refresh) → fallback ~/.codex/auth.json."""
    data = load_tokens("codex")
    if data:
        if data.get("expires_at", 0) - 60 > now():
            return data.get("access_token")
        rt = data.get("refresh_token")
        if rt and (new := _codex_refresh(rt, now)):
            return new["access_token"]
        return data.get("access_token")
    if _CLI_AUTH.exists():  # fallback: token do codex CLI, se existir
        try:
            d = json.loads(_CLI_AUTH.read_text(encoding="utf-8"))
            return d.get("tokens", d).get("access_token")
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _decode_jwt_claims(jwt: str) -> dict:
    try:
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001
        return {}


def codex_account_id() -> str:
    """chatgpt account id (header ChatGPT-Account-Id): do id_token do store → CLI auth.json."""
    data = load_tokens("codex")
    if data:
        idt = (data.get("raw") or {}).get("id_token", "")
        claims = _decode_jwt_claims(idt) if idt else {}
        auth = claims.get("https://api.openai.com/auth", {})
        acc = auth.get("chatgpt_account_id") or claims.get("account_id")
        if acc:
            return acc
    if _CLI_AUTH.exists():
        try:
            d = json.loads(_CLI_AUTH.read_text(encoding="utf-8"))
            t = d.get("tokens", d)
            return t.get("account_id") or d.get("account_id", "")
        except (json.JSONDecodeError, OSError):
            return ""
    return ""


def codex_logged_in() -> bool:
    return has_tokens("codex") or _CLI_AUTH.exists()
