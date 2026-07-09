"""Testes do OAuth MiniMax (protocolo real: user_code flow + refresh), sem rede."""

from __future__ import annotations

import urllib.parse

from okami.llm import oauth_minimax as mm


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "STORE_DIR", tmp_path / "cred")
    import okami.llm.oauth as oauth
    monkeypatch.setattr(oauth, "STORE_DIR", tmp_path / "cred")


def test_inference_base_is_anthropic_protocol_not_v1():
    assert mm.minimax_inference_base("global") == "https://api.minimax.io/anthropic"
    assert mm.minimax_inference_base("cn") == "https://api.minimaxi.com/anthropic"
    assert mm.minimax_inference_base() == "https://api.minimax.io/anthropic"


def test_code_request_is_form_post_with_pkce_and_request_id_header(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    captured = {}

    def fake_post_form(url, fields, extra_headers=None):
        if url.endswith("/oauth/code"):
            captured["url"] = url
            captured["fields"] = fields
            captured["headers"] = extra_headers
            return {
                "user_code": "ABCD-1234",
                "verification_uri": "https://api.minimax.io/verify",
                "state": fields["state"],
                "expired_in": 600,
            }
        # token poll: succeed immediately
        return {"status": "success", "access_token": "AT", "refresh_token": "RT", "expired_in": 900}

    monkeypatch.setattr(mm, "_post_form", fake_post_form)
    emitted = []
    mm.minimax_oauth_login(emitted.append, region="global", now=lambda: 1000.0, sleep=lambda s: None)

    assert captured["url"] == "https://api.minimax.io/oauth/code"
    fields = captured["fields"]
    assert fields["response_type"] == "code"
    assert fields["client_id"] == mm.MINIMAX_CLIENT_ID
    assert fields["scope"] == "group_id profile model.completion"
    assert fields["code_challenge_method"] == "S256"
    assert "code_challenge" in fields and "state" in fields
    assert "x-request-id" in captured["headers"]
    # sanity: x-request-id parses as a uuid4
    import uuid
    uuid.UUID(captured["headers"]["x-request-id"])
    assert any("Código" in m or "ABCD-1234" in m for m in emitted)


def test_poll_pending_then_success(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_post_form(url, fields, extra_headers=None):
        if url.endswith("/oauth/code"):
            return {"user_code": "U1", "verification_uri": "https://x", "expired_in": 600, "state": fields["state"]}
        calls["n"] += 1
        if calls["n"] < 3:
            return {"status": "pending"}
        return {"status": "success", "access_token": "AT2", "refresh_token": "RT2", "expired_in": 900}

    monkeypatch.setattr(mm, "_post_form", fake_post_form)
    clock = [1000.0]
    data = mm.minimax_oauth_login(
        lambda m: None, now=lambda: clock[0],
        sleep=lambda s: clock.__setitem__(0, clock[0] + s),
    )
    assert calls["n"] == 3
    assert data["access_token"] == "AT2"
    assert mm.load_tokens("minimax")["refresh_token"] == "RT2"


def test_poll_error_status_raises_not_rfc_error_field(tmp_path, monkeypatch):
    """MiniMax NÃO usa o `error` clássico do RFC 8628 — usa um campo `status`."""
    _isolate(tmp_path, monkeypatch)

    def fake_post_form(url, fields, extra_headers=None):
        if url.endswith("/oauth/code"):
            return {"user_code": "U1", "verification_uri": "https://x", "expired_in": 600, "state": fields["state"]}
        return {"status": "error"}

    monkeypatch.setattr(mm, "_post_form", fake_post_form)
    try:
        mm.minimax_oauth_login(lambda m: None, now=lambda: 1000.0, sleep=lambda s: None)
        assert False, "deveria levantar RuntimeError"
    except RuntimeError as e:
        assert "erro" in str(e)


def test_code_request_missing_user_code_raises(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(mm, "_post_form", lambda *a, **k: {"status": "error"})
    try:
        mm.minimax_oauth_login(lambda m: None, now=lambda: 1000.0, sleep=lambda s: None)
        assert False, "deveria levantar RuntimeError"
    except RuntimeError as e:
        assert "oauth/code" in str(e)


def test_expired_in_disambiguation_ttl_seconds():
    # TTL plausível (segundos) — bem abaixo do threshold de epoch-ms.
    now = 1_000_000.0
    expires_at = mm._resolve_expires_at(900, now)
    assert expires_at == now + 900


def test_expired_in_disambiguation_ms_epoch():
    # epoch em ms (bem acima de 10**12) — deve virar segundos absolutos, IGNORANDO `now`.
    now = 1_000_000.0
    ms_epoch = 1_800_000_000_000  # ~2027 em ms
    expires_at = mm._resolve_expires_at(ms_epoch, now)
    assert expires_at == ms_epoch / 1000.0
    assert expires_at != now + ms_epoch


def test_looks_like_ms_epoch_boundary():
    assert mm._looks_like_ms_epoch(10**12 + 1) is True
    assert mm._looks_like_ms_epoch(10**12) is False
    assert mm._looks_like_ms_epoch(900) is False


def test_access_token_none_without_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert mm.minimax_access_token(now=lambda: 1000.0) is None


def test_access_token_fresh_no_refresh_call(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    mm.save_tokens("minimax", {"access_token": "FRESH", "refresh_token": "RT", "expires_at": 2000.0})

    def boom(*a, **k):
        raise AssertionError("não deveria chamar refresh com token fresco")

    monkeypatch.setattr(mm, "_post_form", boom)
    # now=1000 → expires_at(2000) - 60 = 1940 > 1000 → válido, sem refresh
    assert mm.minimax_access_token(now=lambda: 1000.0) == "FRESH"


def test_access_token_refreshes_when_near_expiry(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    mm.save_tokens("minimax", {"access_token": "OLD", "refresh_token": "RT", "expires_at": 1000.0})

    captured = {}

    def fake_post_form(url, fields, extra_headers=None):
        captured["url"] = url
        captured["fields"] = fields
        assert url == "https://api.minimax.io/oauth/token"
        assert fields["grant_type"] == "refresh_token"
        assert fields["refresh_token"] == "RT"
        assert fields["client_id"] == mm.MINIMAX_CLIENT_ID
        return {"status": "success", "access_token": "NEW", "refresh_token": "RT2", "expired_in": 900}

    monkeypatch.setattr(mm, "_post_form", fake_post_form)
    # now=999 → expires_at(1000) - 60 = 940 < 999 → precisa refresh
    token = mm.minimax_access_token(now=lambda: 999.0)
    assert token == "NEW"
    assert mm.load_tokens("minimax")["refresh_token"] == "RT2"


def test_access_token_refresh_failure_falls_back_to_stale_token(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    mm.save_tokens("minimax", {"access_token": "STALE", "refresh_token": "RT", "expires_at": 1000.0})
    monkeypatch.setattr(mm, "_post_form", lambda *a, **k: {"status": "error"})
    assert mm.minimax_access_token(now=lambda: 999.0) == "STALE"


def test_force_refresh_minimax(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    mm.save_tokens("minimax", {"access_token": "A", "refresh_token": "RT", "expires_at": 9_999_999_999.0})
    monkeypatch.setattr(
        mm, "_post_form",
        lambda *a, **k: {"status": "success", "access_token": "FORCED", "refresh_token": "RT3", "expired_in": 900},
    )
    assert mm.force_refresh_minimax(now=lambda: 1000.0) == "FORCED"


def test_post_form_real_encoding_and_header(monkeypatch):
    """Sanidade do _post_form real (sem mock): valida shape do corpo/urlopen chamado."""
    import json as _json

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return _json.dumps({"ok": True}).encode()

    captured = {}

    def fake_urlopen(req, timeout=30):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["body"] = req.data
        return FakeResp()

    monkeypatch.setattr(mm.urllib.request, "urlopen", fake_urlopen)
    result = mm._post_form("https://x/y", {"a": "1", "b": "two words"}, extra_headers={"X-Request-Id": "rid"})
    assert result == {"ok": True}
    assert captured["url"] == "https://x/y"
    assert captured["headers"]["X-request-id"] == "rid"
    body = urllib.parse.parse_qs(captured["body"].decode())
    assert body["a"] == ["1"]
    assert body["b"] == ["two words"]
