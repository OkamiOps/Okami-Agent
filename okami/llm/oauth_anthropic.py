"""Login OAuth de assinatura Anthropic (Claude Pro/Max) via PKCE — SEM depender do `claude` CLI.

Espelha o fluxo do Claude Code / Hermes: gera code_verifier+challenge (S256), abre a URL de
autorização, o usuário cola `code#state`, trocamos por access/refresh token e guardamos no
NOSSO store (okami.llm.oauth). Fallback de leitura: ~/.claude/.credentials.json e (macOS)
Keychain "Claude Code-credentials" — para reaproveitar uma sessão já autenticada pelo Claude
Code, sem exigir novo login.

Falha-segura: qualquer erro de rede/parsing devolve None/mensagem clara, nunca propaga
exceção inesperada pro chamador (o login interativo é a exceção — ali reportamos o motivo).
"""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from okami.llm.oauth import (
    STORE_DIR,  # noqa: F401 — reexportado p/ quem importar daqui (mesma fonte única)
    _decode_jwt_claims,  # noqa: F401 — reexportado (não usado diretamente aqui)
    _normalize,
    load_tokens,
    save_tokens,
)

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPES = "org:create_api_key user:profile user:inference"
# platform.claude.com é o host vivo; console.anthropic.com fica de fallback p/ deployments antigos.
TOKEN_URLS = [
    "https://platform.claude.com/v1/oauth/token",
    "https://console.anthropic.com/v1/oauth/token",
]
# Anthropic bloqueia (429) requisições ao token endpoint com UA "claude-code/*"; o Claude Code
# real troca o código com um client axios puro. Mimetizamos isso aqui — NÃO usar o UA de inferência.
_TOKEN_USER_AGENT = "axios/1.7.9"

_CLAUDE_CREDS_FILE = Path.home() / ".claude" / ".credentials.json"
_KEYCHAIN_SERVICE = "Claude Code-credentials"

PROVIDER = "claude"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate_pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge=S256(verifier))."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def build_authorize_url(code_challenge: str, state: str) -> str:
    params = {
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", _TOKEN_USER_AGENT)
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8"))


def _post_token(payload: dict) -> dict:
    """POST no token endpoint tentando platform.claude.com → console.anthropic.com."""
    last_err: Exception | None = None
    for url in TOKEN_URLS:
        try:
            return _post_json(url, payload)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")
            try:
                body = json.loads(detail)
                err = body.get("error") if isinstance(body, dict) else None
                if isinstance(err, dict):
                    err = err.get("code") or err.get("type")
            except (ValueError, TypeError, AttributeError):
                err = None
            last_err = e
            result = {"error": err or f"http_{e.code}", "_status": e.code, "_detail": detail[:300]}
            # 4xx que não seja 404 (host morto) já é resposta "real" do endpoint certo — não itera mais.
            if e.code != 404:
                return result
            continue
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last_err = e
            continue
    return {"error": f"token endpoint unreachable: {last_err}"} if last_err else {"error": "token endpoint unreachable"}


def anthropic_login(
    emit: Callable[[str], None],
    read_code: Callable[[], str] | None = None,
    now: Callable[[], float] = time.time,
) -> dict | None:
    """Fluxo PKCE completo: emite a URL, lê `code#state` colado, troca por tokens e salva.

    `read_code` é injetável p/ teste (default: `input("Authorization code: ")`).
    Devolve os tokens normalizados salvos, ou None em caso de erro (mensagem via `emit`).
    """
    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(32)
    url = build_authorize_url(challenge, state)

    emit(
        "Abra esta URL, autorize e cole o código exibido (formato code#state):\n"
        f"{url}"
    )

    reader = read_code or (lambda: input("Authorization code: "))
    try:
        pasted = (reader() or "").strip()
    except (KeyboardInterrupt, EOFError):
        emit("Login cancelado.")
        return None

    if not pasted:
        emit("Nenhum código informado.")
        return None

    parts = pasted.split("#", 1)
    code = parts[0]
    received_state = parts[1] if len(parts) > 1 else ""
    if received_state != state:
        emit("Estado OAuth não confere (possível CSRF) — login abortado.")
        return None

    tok = _post_token({
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "state": received_state,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    })
    if "access_token" not in tok:
        emit(f"Troca de código falhou: {tok}")
        return None

    data = _normalize(tok, now())
    save_tokens(PROVIDER, data)
    emit("Login Anthropic concluído — assinatura conectada.")
    return data


def _refresh(refresh_token: str, now: Callable[[], float]) -> dict | None:
    tok = _post_token({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": refresh_token,
    })
    if "access_token" not in tok:
        return None
    new = _normalize(tok, now())
    new["refresh_token"] = new.get("refresh_token") or refresh_token
    save_tokens(PROVIDER, new)
    return new


def _store_token(now: Callable[[], float]) -> tuple[str | None, int]:
    """(access_token, expires_at) do NOSSO store, com refresh se necessário. expires_at em segundos epoch."""
    data = load_tokens(PROVIDER)
    if not data:
        return None, 0
    if data.get("expires_at", 0) - 60 > now():
        return data.get("access_token"), int(data.get("expires_at", 0))
    rt = data.get("refresh_token")
    if rt:
        new = _refresh(rt, now)
        if new:
            return new.get("access_token"), int(new.get("expires_at", 0))
    # expirado e sem refresh que preste — não é "válido"; deixa o fallback decidir.
    return None, 0


def _read_claude_credentials_file() -> dict | None:
    if not _CLAUDE_CREDS_FILE.exists():
        return None
    try:
        data = json.loads(_CLAUDE_CREDS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    oauth_data = data.get("claudeAiOauth")
    if not isinstance(oauth_data, dict):
        return None
    at = oauth_data.get("accessToken")
    if not at:
        return None
    return {
        "accessToken": at,
        "refreshToken": oauth_data.get("refreshToken", ""),
        "expiresAt": oauth_data.get("expiresAt", 0),
    }


def _read_claude_credentials_keychain() -> dict | None:
    if platform.system() != "Darwin":
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", _KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    raw = (result.stdout or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    oauth_data = data.get("claudeAiOauth")
    if not isinstance(oauth_data, dict):
        return None
    at = oauth_data.get("accessToken")
    if not at:
        return None
    return {
        "accessToken": at,
        "refreshToken": oauth_data.get("refreshToken", ""),
        "expiresAt": oauth_data.get("expiresAt", 0),
    }


def _claude_cli_token(now: Callable[[], float]) -> tuple[str | None, int]:
    """Melhor token entre ~/.claude/.credentials.json e Keychain (o que expira mais tarde e ainda vale)."""
    file_creds = _read_claude_credentials_file()
    kc_creds = _read_claude_credentials_keychain()
    now_ms = now() * 1000

    def valid(c: dict | None) -> bool:
        if not c:
            return False
        exp = c.get("expiresAt", 0) or 0
        if not exp:
            return bool(c.get("accessToken"))
        return now_ms < (exp - 60_000)

    candidates = [c for c in (file_creds, kc_creds) if valid(c)]
    if not candidates:
        return None, 0
    best = max(candidates, key=lambda c: c.get("expiresAt", 0) or 0)
    return best.get("accessToken"), int((best.get("expiresAt", 0) or 0) / 1000)


def anthropic_access_token(now: Callable[[], float] = time.time) -> str | None:
    """Token Bearer válido: nosso store (com refresh) → ~/.claude/.credentials.json / Keychain.

    Entre store e fallback CLI, prefere o que expira mais tarde (evita devolver um token
    prestes a expirar quando há outro mais fresco disponível)."""
    store_tok, store_exp = _store_token(now)
    cli_tok, cli_exp = _claude_cli_token(now)

    if store_tok and cli_tok:
        return store_tok if store_exp >= cli_exp else cli_tok
    return store_tok or cli_tok


def anthropic_inference_headers(token: str) -> dict:
    """Headers p/ chamar api.anthropic.com com um token OAuth (Bearer).

    ATENÇÃO: esse caminho é OAuth (assinatura) — usa `authorization: Bearer`. O caminho de
    API key normal usa o header `x-api-key` em vez deste; não misturar os dois.
    """
    return {
        "authorization": f"Bearer {token}",
        "user-agent": "claude-code/1.0 (external, cli)",
        "x-app": "cli",
        "anthropic-beta": "oauth-2025-04-20",
    }
