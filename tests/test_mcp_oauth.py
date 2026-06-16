"""#11 Onda 4: MCP OAuth 2.1 + PKCE (port do Hermes tools/mcp_oauth.py) — p/ MCP protegido por OAuth
(GitHub/Google-backed) em vez de bearer estático. Testa o core puro (PKCE, URL, exchange, refresh, store);
o passo interativo (browser + callback localhost) é wrapper fino."""
from __future__ import annotations

import base64
import hashlib


def test_pkce_challenge_is_s256_of_verifier():
    from okami.integrations.mcp_oauth import generate_pkce
    verifier, challenge, method = generate_pkce()
    assert method == "S256"
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected
    assert 43 <= len(verifier) <= 128                # RFC 7636


def test_build_authorization_url_has_pkce_params():
    from urllib.parse import parse_qs, urlparse
    from okami.integrations.mcp_oauth import build_authorization_url
    url = build_authorization_url("https://idp/authorize", client_id="cid", redirect_uri="http://localhost:8765/cb",
                                  challenge="abc", scope="read", state="xyz")
    q = parse_qs(urlparse(url).query)
    assert q["code_challenge"] == ["abc"] and q["code_challenge_method"] == ["S256"]
    assert q["client_id"] == ["cid"] and q["response_type"] == ["code"] and q["state"] == ["xyz"]


def test_exchange_code_posts_verifier():
    from okami.integrations.mcp_oauth import exchange_code
    seen = {}
    def fake_post(url, data):
        seen.update(url=url, data=data)
        return {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}
    tok = exchange_code("https://idp/token", client_id="cid", code="CODE", verifier="VER",
                        redirect_uri="http://localhost/cb", _post=fake_post)
    assert tok["access_token"] == "AT"
    assert seen["data"]["grant_type"] == "authorization_code" and seen["data"]["code_verifier"] == "VER"


def test_refresh_token_posts_grant():
    from okami.integrations.mcp_oauth import refresh_token
    seen = {}
    def fake_post(url, data):
        seen.update(data=data)
        return {"access_token": "AT2", "expires_in": 3600}
    tok = refresh_token("https://idp/token", client_id="cid", refresh_token="RT", _post=fake_post)
    assert tok["access_token"] == "AT2" and seen["data"]["grant_type"] == "refresh_token"


def test_token_store_roundtrip(tmp_path):
    from okami.integrations.mcp_oauth import TokenStore
    st = TokenStore(tmp_path)
    st.save("github", {"access_token": "AT", "refresh_token": "RT", "expires_at": 9999999999})
    got = st.load("github")
    assert got["access_token"] == "AT"
    assert st.load("inexistente") is None


def test_token_store_valid_access_token_respects_expiry(tmp_path):
    from okami.integrations.mcp_oauth import TokenStore
    st = TokenStore(tmp_path)
    st.save("a", {"access_token": "FRESH", "expires_at": 9999999999})
    st.save("b", {"access_token": "STALE", "expires_at": 1})
    assert st.valid_access_token("a", now=1000) == "FRESH"
    assert st.valid_access_token("b", now=1000) is None      # expirado → None (caller faz refresh)


def test_oauth_bearer_refreshes_expired(tmp_path):
    from okami.integrations.mcp_oauth import TokenStore, oauth_bearer
    st = TokenStore(tmp_path)
    st.save("gh", {"access_token": "OLD", "refresh_token": "RT", "expires_at": 1})
    conf = {"oauth": {"token_endpoint": "https://idp/token", "client_id": "cid"}}
    bearer = oauth_bearer("gh", conf, st, now=1000, _post=lambda u, d: {"access_token": "NEW", "expires_in": 3600})
    assert bearer == "NEW"                                    # expirado + refresh_token → renova
    assert st.valid_access_token("gh", now=1000) == "NEW"     # persistiu o novo


def test_oauth_bearer_none_without_refresh(tmp_path):
    from okami.integrations.mcp_oauth import TokenStore, oauth_bearer
    st = TokenStore(tmp_path)
    assert oauth_bearer("vazio", {}, st, now=1000) is None    # sem token e sem refresh → precisa autorizar
