"""Testes do subsistema OAuth (store + validade), sem rede."""

from __future__ import annotations

from okami.llm import oauth


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "STORE_DIR", tmp_path / "cred")


def test_store_roundtrip(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert oauth.load_tokens("p") is None
    assert oauth.has_tokens("p") is False
    oauth.save_tokens("p", {"access_token": "abc", "expires_at": 9_999_999_999})
    assert oauth.has_tokens("p") is True
    assert oauth.load_tokens("p")["access_token"] == "abc"


def test_get_valid_token_when_fresh(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    oauth.save_tokens("p", {"access_token": "tok", "expires_at": 1000})
    # now=900 → expires_at(1000) - 60 = 940 > 900 → válido
    assert oauth.get_valid_token("p", None, now=lambda: 900.0) == "tok"


def test_get_valid_token_none_without_store(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert oauth.get_valid_token("missing", None) is None


def test_expired_without_refresh_returns_best_effort(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    oauth.save_tokens("p", {"access_token": "old", "expires_at": 1000})
    # now=2000 → expirado, sem refresh_token/oauth → devolve o que tem (best-effort)
    assert oauth.get_valid_token("p", None, now=lambda: 2000.0) == "old"


def test_codex_native_device_flow(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(oauth, "_CLI_AUTH", tmp_path / "no_cli.json")
    polls = {"n": 0}

    def fake_post_json(url, payload):
        if url.endswith("/usercode"):
            return {"device_auth_id": "D1", "user_code": "WXYZ", "interval": 1, "expires_in": 100}
        if url.endswith("/deviceauth/token"):
            polls["n"] += 1
            if polls["n"] < 2:
                return {"error": "authorization_pending"}
            return {"authorization_code": "AC", "code_verifier": "CV"}
        return {}

    def fake_post_form(url, fields):
        assert fields["grant_type"] == "authorization_code"
        assert fields["code"] == "AC" and fields["code_verifier"] == "CV"
        return {"access_token": "AT", "refresh_token": "RT", "id_token": "h.y.s", "expires_in": 3600}

    monkeypatch.setattr(oauth, "_post_json", fake_post_json)
    monkeypatch.setattr(oauth, "_post_form", fake_post_form)
    clock = [1000.0]
    data = oauth.codex_device_login(
        lambda m: None, now=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s)
    )
    assert data["access_token"] == "AT"
    assert oauth.load_tokens("codex")["refresh_token"] == "RT"
    assert oauth.codex_access_token(now=lambda: clock[0]) == "AT"


def test_codex_access_token_refreshes_expired_cli_authjson(tmp_path, monkeypatch):
    """auth.json copiado de outra máquina (token expirado) → renova via refresh_token."""
    import base64
    import json as _json

    _isolate(tmp_path, monkeypatch)
    # access_token expirado (exp no passado) + refresh_token, no formato do codex CLI.
    claims = {"exp": 1000}
    payload = base64.urlsafe_b64encode(_json.dumps(claims).encode()).decode().rstrip("=")
    auth = tmp_path / "auth.json"
    auth.write_text(_json.dumps({"tokens": {"access_token": f"h.{payload}.s",
                                            "refresh_token": "RT"}}))
    monkeypatch.setattr(oauth, "_CLI_AUTH", auth)
    monkeypatch.setattr(oauth, "_codex_refresh",
                        lambda rt, now: {"access_token": "FRESH"} if rt == "RT" else None)
    # now=5000 > exp(1000) → expirado → usa o refresh
    assert oauth.codex_access_token(now=lambda: 5000.0) == "FRESH"


def test_codex_account_id_from_id_token(tmp_path, monkeypatch):
    import base64
    import json as _json

    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(oauth, "_CLI_AUTH", tmp_path / "no_cli.json")
    claims = {"https://api.openai.com/auth": {"chatgpt_account_id": "ACC9"}}
    payload = base64.urlsafe_b64encode(_json.dumps(claims).encode()).decode().rstrip("=")
    oauth.save_tokens("codex", {"access_token": "a", "expires_at": 9_999_999_999,
                                "raw": {"id_token": f"h.{payload}.s"}})
    assert oauth.codex_account_id() == "ACC9"
