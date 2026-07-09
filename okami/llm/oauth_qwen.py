"""Qwen — SEM login próprio: lê o arquivo de credenciais do Qwen CLI (`~/.qwen/oauth_creds.json`).

O Okami não implementa o device flow da Qwen (fluxo próprio do `qwen` CLI, com PKCE contra
chat.qwen.ai). Em vez de duplicar isso, lemos o arquivo que o `qwen` CLI já escreve depois de um
`qwen` login bem-sucedido — mesma ideia do fallback `~/.codex/auth.json` em `okami.llm.oauth`.

Diferença importante: aqui o arquivo NÃO é nosso (`credentials_dir()`/`save_tokens`) — é do Qwen
CLI. Por isso o refresh grava de volta NO MESMO ARQUIVO (atômico + 0600), preservando quaisquer
outras chaves que o Qwen CLI tenha colocado lá (ex.: `resource_url`, `token_type`) em vez de
sobrescrever com um dict enxuto só nosso.

Falha-segura: arquivo ausente → None (usuário precisa rodar `qwen` login primeiro; emite dica via
`hint`, não levanta exceção) — nunca propaga erro de rede/parsing pro chamador.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from okami.core.safe_io import write_atomic

QWEN_CREDS_FILE = Path.home() / ".qwen" / "oauth_creds.json"
QWEN_TOKEN_URL = "https://chat.qwen.ai/api/v1/oauth2/token"
QWEN_CLIENT_ID = "f0304373b74a44d2b584a3fb70ca9e56"
QWEN_INFERENCE_BASE = "https://portal.qwen.ai/v1"

# dica emitida quando o arquivo de credenciais do Qwen CLI não existe — sem isso o usuário só vê
# "None" e não sabe que precisa logar no CLI oficial primeiro.
QWEN_LOGIN_HINT = "Credenciais do Qwen não encontradas — rode `qwen` (login) para autenticar primeiro."


def _read_creds() -> dict | None:
    if not QWEN_CREDS_FILE.exists():
        return None
    try:
        data = json.loads(QWEN_CREDS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _save_creds(data: dict) -> None:
    write_atomic(QWEN_CREDS_FILE, json.dumps(data, indent=2), mode=0o600)  # preserva o resto do arquivo


def _expiring(expiry_date_ms, now: float) -> bool:
    try:
        exp_ms = int(expiry_date_ms)
    except (TypeError, ValueError):
        return True
    return (now + 60) * 1000 >= exp_ms  # 60s de folga, mesma convenção do resto do okami/llm/oauth.py


def _post_refresh(refresh_token: str) -> dict:
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": QWEN_CLIENT_ID,
        "refresh_token": refresh_token,
    }).encode("utf-8")
    req = urllib.request.Request(QWEN_TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "ignore"))
        except (json.JSONDecodeError, TypeError):
            return {"error": f"http_{e.code}"}
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return {"error": f"qwen refresh unreachable: {e}"}


def qwen_access_token(now: Callable[[], float] = time.time,
                      hint: Callable[[str], None] | None = None) -> str | None:
    """access_token válido do arquivo do Qwen CLI; refresh (grava de volta) se expirando.

    None se o arquivo não existir (chama `hint(...)` com a dica de login, se fornecido) ou se
    faltar access_token utilizável mesmo depois de tentar refresh."""
    creds = _read_creds()
    if creds is None:
        if hint:
            hint(QWEN_LOGIN_HINT)
        return None

    at = creds.get("access_token")
    rt = creds.get("refresh_token")
    exp = creds.get("expiry_date")

    if at and not _expiring(exp, now()):
        return at

    if not rt:
        return at  # sem refresh possível — melhor-esforço com o que tem (pode já estar expirado)

    tok = _post_refresh(rt)
    new_at = tok.get("access_token")
    if not new_at:
        return at  # refresh falhou — melhor-esforço, não perde o token antigo

    expires_in = tok.get("expires_in")
    try:
        expires_in_s = int(expires_in)
    except (TypeError, ValueError):
        expires_in_s = 6 * 60 * 60  # 6h — mesma janela default do Qwen CLI

    merged = dict(creds)  # preserva chaves extras do Qwen CLI (resource_url, token_type, ...)
    merged["access_token"] = new_at
    merged["refresh_token"] = tok.get("refresh_token") or rt
    merged["expiry_date"] = int(now() * 1000) + expires_in_s * 1000
    if "token_type" in tok:
        merged["token_type"] = tok["token_type"]
    _save_creds(merged)
    return new_at


def qwen_inference_base() -> str:
    return QWEN_INFERENCE_BASE
