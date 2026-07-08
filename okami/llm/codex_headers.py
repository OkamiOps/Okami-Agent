"""Headers anti-Cloudflare p/ `chatgpt.com/backend-api/codex/*` (chat E image_generation).

O Cloudflare na frente desse host libera só um punhado de originators de primeira parte
(`codex_cli_rs`, `codex_vscode`, `codex_sdk_ts`, …). Requests de IP não-residencial (VPS — que é
onde o Okami roda, ver memória "Okami VPS-first") sem um originator permitido levam 403
`cf-mitigated: challenge` MESMO com um Bearer token válido — não é problema de auth, é o gate na
frente (Hermes `agent/auxiliary_client.py:663-700`, função `_codex_cloudflare_headers`).

Fixamos `originator: codex_cli_rs` (o mesmo do CLI oficial do Codex), um `User-Agent` no formato
`codex_cli_rs/<versão> (...)`, e extraímos `ChatGPT-Account-Id` do claim
`https://api.openai.com/auth.chatgpt_account_id` dentro do JWT de acesso (mesmo claim que o
Codex CLI usa em `auth.rs`).

Reusa `okami.llm.oauth.codex_access_token()` p/ obter o token; `account_id_from_token` decodifica
o JWT sem depender de rede (é local, o claim já está embutido no token).
"""

from __future__ import annotations

import base64
import json

# String-alvo do fingerprint de UA que o Cloudflare aceita (mesma família do codex-rs oficial).
# A versão em si não é validada pelo gate — só o formato/prefixo "codex_cli_rs/".
CODEX_CLI_VERSION = "0.1.0"
CODEX_ORIGINATOR = "codex_cli_rs"


def _decode_jwt_claims(token: str) -> dict:
    """Decodifica o payload (2º segmento) de um JWT sem validar assinatura (não precisamos —
    só lemos um claim público embutido). Token malformado/vazio → {} (nunca derruba a chamada)."""
    if not isinstance(token, str) or not token:
        return {}
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)   # padding do base64url
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001 — token estranho não pode quebrar a chamada, só perde o header opcional
        return {}


def account_id_from_token(access_token: str) -> str:
    """Extrai `chatgpt_account_id` do claim `https://api.openai.com/auth` do JWT de acesso.
    Vazio se o claim não existir (token de outro fluxo, malformado, etc.)."""
    claims = _decode_jwt_claims(access_token)
    auth = claims.get("https://api.openai.com/auth")
    acc = auth.get("chatgpt_account_id") if isinstance(auth, dict) else None
    return acc if isinstance(acc, str) and acc else ""


def cloudflare_headers(access_token: str | None, account_id: str | None = None) -> dict[str, str]:
    """Monta os headers que passam no gate do Cloudflare p/ chatgpt.com/backend-api/codex.

    `account_id`: se o chamador já tem o account id por outra via (ex.: id_token, já decodificado
    em `oauth.codex_account_id()`), passa aqui e pula a decodificação do access_token. Se omitido,
    tenta extrair do próprio `access_token`.
    """
    headers = {
        "User-Agent": f"{CODEX_ORIGINATOR}/{CODEX_CLI_VERSION} (Okami Agent)",
        "originator": CODEX_ORIGINATOR,
    }
    acc = account_id or account_id_from_token(access_token or "")
    if not acc:
        # Claim ausente no JWT (caso normal do codex CLI — o account fica em ~/.codex/auth.json,
        # não no token). Resolve pela via do oauth (store → auth.json tokens.account_id).
        try:
            from okami.llm import oauth
            acc = oauth.codex_account_id()
        except Exception:  # noqa: BLE001 — resolução best-effort; sem account só perde o header opcional
            acc = ""
    if acc:
        headers["ChatGPT-Account-Id"] = acc
    return headers


__all__ = ["cloudflare_headers", "account_id_from_token", "CODEX_ORIGINATOR", "CODEX_CLI_VERSION"]
