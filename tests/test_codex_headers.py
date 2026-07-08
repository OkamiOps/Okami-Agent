"""Headers anti-Cloudflare (`codex_headers.py`) — gate na frente de chatgpt.com/backend-api/codex
que derruba requests de VPS sem originator de primeira parte, mesmo com token válido (ver docstring
do módulo)."""
from __future__ import annotations

import base64
import json


def _jwt(claims: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


def test_account_id_from_token_reads_chatgpt_account_id_claim():
    from okami.llm.codex_headers import account_id_from_token
    tok = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-123"}})
    assert account_id_from_token(tok) == "acct-123"


def test_account_id_from_token_missing_claim_is_empty():
    from okami.llm.codex_headers import account_id_from_token
    tok = _jwt({"sub": "user-1"})
    assert account_id_from_token(tok) == ""


def test_account_id_from_token_malformed_does_not_raise():
    from okami.llm.codex_headers import account_id_from_token
    assert account_id_from_token("not-a-jwt") == ""
    assert account_id_from_token("") == ""
    assert account_id_from_token(None) == ""  # type: ignore[arg-type]


def test_cloudflare_headers_sets_originator_and_user_agent():
    from okami.llm.codex_headers import cloudflare_headers
    h = cloudflare_headers("tok")
    assert h["originator"] == "codex_cli_rs"
    assert h["User-Agent"].startswith("codex_cli_rs/")


def test_cloudflare_headers_extracts_account_id_from_token():
    from okami.llm.codex_headers import cloudflare_headers
    tok = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-999"}})
    h = cloudflare_headers(tok)
    assert h["ChatGPT-Account-Id"] == "acct-999"


def test_cloudflare_headers_prefers_explicit_account_id_over_token_claim():
    from okami.llm.codex_headers import cloudflare_headers
    tok = _jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "from-token"}})
    h = cloudflare_headers(tok, account_id="from-caller")
    assert h["ChatGPT-Account-Id"] == "from-caller"


def test_cloudflare_headers_no_account_id_when_unavailable(monkeypatch):
    # claim ausente no JWT E resolução via oauth vazia (nem store nem ~/.codex/auth.json) → sem header.
    from okami.llm import oauth
    monkeypatch.setattr(oauth, "codex_account_id", lambda *a, **k: "")
    from okami.llm.codex_headers import cloudflare_headers
    h = cloudflare_headers("not-a-jwt")
    assert "ChatGPT-Account-Id" not in h
