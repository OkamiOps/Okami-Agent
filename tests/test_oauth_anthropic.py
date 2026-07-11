"""Testes do login OAuth de assinatura Anthropic (PKCE, sem `claude` CLI) — sem rede real."""

from __future__ import annotations

import base64
import hashlib
import urllib.parse

from okami.llm import oauth_anthropic as oa


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(oa, "STORE_DIR", tmp_path / "cred")
    # oauth.py's save_tokens/load_tokens read from oauth.STORE_DIR directly, so patch there too.
    from okami.llm import oauth as oauth_mod
    monkeypatch.setattr(oauth_mod, "STORE_DIR", tmp_path / "cred")


def test_pkce_challenge_is_valid_s256_of_verifier():
    verifier, challenge = oa.generate_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    assert challenge == expected
    assert "=" not in verifier and "=" not in challenge


def test_authorize_url_has_all_params():
    url = oa.build_authorize_url("CHALLENGE123", "STATE456")
    prefix, query = url.split("?", 1)
    assert prefix == oa.AUTHORIZE_URL
    params = dict(urllib.parse.parse_qsl(query))
    assert params["code"] == "true"
    assert params["client_id"] == oa.CLIENT_ID
    assert params["response_type"] == "code"
    assert params["redirect_uri"] == oa.REDIRECT_URI
    assert params["scope"] == oa.SCOPES
    assert params["code_challenge"] == "CHALLENGE123"
    assert params["code_challenge_method"] == "S256"
    assert params["state"] == "STATE456"


def test_login_splits_code_hash_state_and_saves_tokens(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    captured = {}

    def fake_post_token(payload):
        captured["payload"] = payload
        assert payload["grant_type"] == "authorization_code"
        assert payload["client_id"] == oa.CLIENT_ID
        assert payload["redirect_uri"] == oa.REDIRECT_URI
        return {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}

    monkeypatch.setattr(oa, "_post_token", fake_post_token)

    # Force a known state by patching secrets.token_urlsafe used inside anthropic_login.
    monkeypatch.setattr(oa.secrets, "token_urlsafe", lambda n: "FIXEDSTATE")

    emitted = []
    data = oa.anthropic_login(
        emit=emitted.append,
        read_code=lambda: "AUTHCODE123#FIXEDSTATE",
        now=lambda: 1000.0,
    )

    assert data is not None
    assert data["access_token"] == "AT"
    assert data["refresh_token"] == "RT"
    assert captured["payload"]["code"] == "AUTHCODE123"
    assert captured["payload"]["state"] == "FIXEDSTATE"
    assert oa.load_tokens(oa.PROVIDER)["access_token"] == "AT"
    assert any("concluído" in m for m in emitted)


def test_login_state_mismatch_aborts(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(oa.secrets, "token_urlsafe", lambda n: "REALSTATE")
    called = {"post": False}
    monkeypatch.setattr(oa, "_post_token", lambda payload: called.__setitem__("post", True) or {})

    emitted = []
    data = oa.anthropic_login(emit=emitted.append, read_code=lambda: "CODE#WRONGSTATE")
    assert data is None
    assert called["post"] is False
    assert oa.load_tokens(oa.PROVIDER) is None


def test_login_no_code_entered(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    emitted = []
    data = oa.anthropic_login(emit=emitted.append, read_code=lambda: "   ")
    assert data is None


def test_access_token_prefers_store_when_valid(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    oa.save_tokens(oa.PROVIDER, {"access_token": "STORE_TOK", "expires_at": 10_000})
    monkeypatch.setattr(oa, "_read_claude_credentials_file", lambda: None)
    monkeypatch.setattr(oa, "_read_claude_credentials_keychain", lambda: None)
    # now=9000 -> expires_at(10000)-60=9940 > 9000 -> válido
    assert oa.anthropic_access_token(now=lambda: 9000.0) == "STORE_TOK"


def test_access_token_falls_back_to_claude_credentials_file(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert oa.load_tokens(oa.PROVIDER) is None
    monkeypatch.setattr(oa, "_read_claude_credentials_file", lambda: {
        "accessToken": "FILE_TOK", "refreshToken": "", "expiresAt": 99_999_999_999,
    })
    monkeypatch.setattr(oa, "_read_claude_credentials_keychain", lambda: None)
    assert oa.anthropic_access_token(now=lambda: 1000.0) == "FILE_TOK"


def test_access_token_falls_back_to_keychain(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(oa, "_read_claude_credentials_file", lambda: None)
    monkeypatch.setattr(oa, "_read_claude_credentials_keychain", lambda: {
        "accessToken": "KC_TOK", "refreshToken": "", "expiresAt": 99_999_999_999,
    })
    assert oa.anthropic_access_token(now=lambda: 1000.0) == "KC_TOK"


def test_access_token_none_when_nothing_valid(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(oa, "_read_claude_credentials_file", lambda: None)
    monkeypatch.setattr(oa, "_read_claude_credentials_keychain", lambda: None)
    assert oa.anthropic_access_token(now=lambda: 1000.0) is None


def test_access_token_refreshes_expired_store_token(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    oa.save_tokens(oa.PROVIDER, {"access_token": "OLD", "refresh_token": "RT", "expires_at": 1000})
    monkeypatch.setattr(oa, "_read_claude_credentials_file", lambda: None)
    monkeypatch.setattr(oa, "_read_claude_credentials_keychain", lambda: None)

    def fake_post_token(payload):
        assert payload["grant_type"] == "refresh_token"
        assert payload["refresh_token"] == "RT"
        return {"access_token": "NEW", "refresh_token": "RT2", "expires_in": 3600}

    monkeypatch.setattr(oa, "_post_token", fake_post_token)
    # now=2000 -> expirado (1000-60=940 < 2000) -> refresh
    assert oa.anthropic_access_token(now=lambda: 2000.0) == "NEW"
    assert oa.load_tokens(oa.PROVIDER)["refresh_token"] == "RT2"


def test_inference_headers_shape():
    headers = oa.anthropic_inference_headers("MYTOKEN")
    assert headers["authorization"] == "Bearer MYTOKEN"
    assert "x-api-key" not in headers
    assert headers["anthropic-beta"] == "oauth-2025-04-20"
    assert headers["x-app"] == "cli"
    assert "claude-code" in headers["user-agent"]
