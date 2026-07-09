"""Testes do device OAuth Nous e do fallback de credenciais Qwen — sem rede real."""

from __future__ import annotations

import json

from okami.llm import oauth, oauth_nous, oauth_qwen


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "STORE_DIR", tmp_path / "cred")


# ---------------------------------------------------------------------------
# Nous — device flow: pending → success
# ---------------------------------------------------------------------------

def test_nous_login_device_poll_pending_then_success(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    polls = {"n": 0}

    def fake_post_form(url, fields):
        if url == oauth_nous.NOUS_DEVICE_CODE_URL:
            assert fields["client_id"] == oauth_nous.NOUS_CLIENT_ID
            assert fields["scope"] == oauth_nous.NOUS_SCOPE
            return {
                "device_code": "DC1", "user_code": "ABCD",
                "verification_uri": "https://portal.nousresearch.com/device",
                "verification_uri_complete": "https://portal.nousresearch.com/device?code=ABCD",
                "interval": 1, "expires_in": 100,
            }
        if url == oauth_nous.NOUS_TOKEN_URL:
            assert fields["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"
            assert fields["device_code"] == "DC1"
            polls["n"] += 1
            if polls["n"] < 3:
                return {"error": "authorization_pending"}
            return {"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600}
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(oauth_nous, "_post_form", fake_post_form)
    clock = [1000.0]
    emitted = []
    data = oauth_nous.nous_login(
        emitted.append, now=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s)
    )
    assert data["access_token"] == "AT1"
    assert polls["n"] == 3
    assert any("ABCD" in m for m in emitted)
    stored = oauth.load_tokens("nous")
    assert stored["access_token"] == "AT1"
    assert stored["refresh_token"] == "RT1"


def test_nous_login_raises_on_fatal_error(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    def fake_post_form(url, fields):
        if url == oauth_nous.NOUS_DEVICE_CODE_URL:
            return {"device_code": "DC1", "user_code": "ABCD", "interval": 1, "expires_in": 100}
        return {"error": "access_denied"}

    monkeypatch.setattr(oauth_nous, "_post_form", fake_post_form)
    clock = [1000.0]
    try:
        oauth_nous.nous_login(lambda m: None, now=lambda: clock[0],
                              sleep=lambda s: clock.__setitem__(0, clock[0] + s))
        raise AssertionError("deveria ter levantado RuntimeError")
    except RuntimeError as e:
        assert "access_denied" in str(e)


# ---------------------------------------------------------------------------
# Nous — refresh via header x-nous-refresh-token (não body)
# ---------------------------------------------------------------------------

def test_nous_refresh_uses_header_not_body(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    oauth.save_tokens("nous", {"access_token": "old", "refresh_token": "RTOLD", "expires_at": 1000})

    captured = {}

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=30):
        captured["headers"] = dict(req.header_items())
        captured["body"] = req.data.decode("utf-8")
        captured["url"] = req.full_url
        return FakeResp({"access_token": "NEWAT", "refresh_token": "NEWRT", "expires_in": 3600})

    monkeypatch.setattr(oauth_nous.urllib.request, "urlopen", fake_urlopen)

    tok = oauth_nous.nous_access_token(now=lambda: 2000.0)  # expirado (1000-60 < 2000)
    assert tok == "NEWAT"
    # refresh_token vai no HEADER (case-insensitive: urllib title-cases 'X-Nous-Refresh-Token')
    headers_lower = {k.lower(): v for k, v in captured["headers"].items()}
    assert headers_lower["x-nous-refresh-token"] == "RTOLD"
    assert "RTOLD" not in captured["body"]  # NÃO vai no corpo
    assert "refresh_token=RTOLD" not in captured["body"]
    stored = oauth.load_tokens("nous")
    assert stored["access_token"] == "NEWAT"
    assert stored["refresh_token"] == "NEWRT"


def test_nous_refresh_token_reused_clears_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    oauth.save_tokens("nous", {"access_token": "old", "refresh_token": "RTOLD", "expires_at": 1000})

    monkeypatch.setattr(oauth_nous, "_post_refresh", lambda rt: {"error": "refresh_token_reused"})

    tok = oauth_nous.nous_access_token(now=lambda: 2000.0)
    assert tok is None
    assert oauth.load_tokens("nous") is None  # store limpo — precisa relogar


def test_nous_inference_base():
    assert oauth_nous.nous_inference_base() == "https://inference-api.nousresearch.com/v1"


# ---------------------------------------------------------------------------
# Qwen — le arquivo do CLI, refresh grava de volta preservando outras chaves
# ---------------------------------------------------------------------------

def test_qwen_reads_creds_file(tmp_path, monkeypatch):
    creds_path = tmp_path / "oauth_creds.json"
    creds_path.write_text(json.dumps({
        "access_token": "AT", "refresh_token": "RT",
        "expiry_date": 99_999_999_999_999,  # bem no futuro (ms epoch)
        "resource_url": "portal.qwen.ai",
    }))
    monkeypatch.setattr(oauth_qwen, "QWEN_CREDS_FILE", creds_path)

    tok = oauth_qwen.qwen_access_token(now=lambda: 1_000_000.0)
    assert tok == "AT"


def test_qwen_refresh_writes_back_preserving_other_keys(tmp_path, monkeypatch):
    creds_path = tmp_path / "oauth_creds.json"
    original = {
        "access_token": "OLDAT", "refresh_token": "RT",
        "expiry_date": 1000,  # ms epoch, já expirado
        "resource_url": "portal.qwen.ai",
        "token_type": "Bearer",
    }
    creds_path.write_text(json.dumps(original))
    monkeypatch.setattr(oauth_qwen, "QWEN_CREDS_FILE", creds_path)

    def fake_post_refresh(rt):
        assert rt == "RT"
        return {"access_token": "NEWAT", "refresh_token": "NEWRT", "expires_in": 3600}

    monkeypatch.setattr(oauth_qwen, "_post_refresh", fake_post_refresh)

    tok = oauth_qwen.qwen_access_token(now=lambda: 2_000_000.0)
    assert tok == "NEWAT"

    on_disk = json.loads(creds_path.read_text())
    assert on_disk["access_token"] == "NEWAT"
    assert on_disk["refresh_token"] == "NEWRT"
    assert on_disk["resource_url"] == "portal.qwen.ai"  # chave preservada
    assert on_disk["token_type"] == "Bearer"            # chave preservada
    assert on_disk["expiry_date"] == int(2_000_000.0 * 1000) + 3600 * 1000
    # 0600
    import stat
    mode = stat.S_IMODE(creds_path.stat().st_mode)
    assert mode == 0o600


def test_qwen_absent_file_returns_none_with_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth_qwen, "QWEN_CREDS_FILE", tmp_path / "missing" / "oauth_creds.json")
    hints = []
    tok = oauth_qwen.qwen_access_token(now=lambda: 1000.0, hint=hints.append)
    assert tok is None
    assert hints and "qwen" in hints[0].lower()


def test_qwen_inference_base():
    assert oauth_qwen.qwen_inference_base() == "https://portal.qwen.ai/v1"
