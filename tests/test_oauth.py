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


# ── regressão: o estado "pending" do device flow chega como ERRO HTTP (403) com o motivo no CORPO.
# Antes, o poll tratava isso como fatal e ABORTAVA o login (o link aparecia e morria na 1ª batida).

def test_err_payload_unwraps_nested_and_flat_oauth_error():
    # OpenAI: 403 + {"error":{"code":"deviceauth_authorization_pending"}}  → extrai o code REAL
    nested = oauth._err_payload(403, '{"error":{"code":"deviceauth_authorization_pending","message":"x"}}')
    assert nested["error"] == "deviceauth_authorization_pending" and nested["_status"] == 403
    # RFC clássico flat: {"error":"slow_down"}
    assert oauth._err_payload(400, '{"error":"slow_down"}')["error"] == "slow_down"
    # corpo não-JSON / vazio → cai no http_<code> (não explode)
    assert oauth._err_payload(500, "<html>boom</html>")["error"] == "http_500"
    assert oauth._err_payload(403, "")["error"] == "http_403"


def test_codex_device_login_keeps_polling_through_403_pending(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(oauth, "_CLI_AUTH", tmp_path / "no_cli.json")
    polls = {"n": 0}

    def fake_post_json(url, payload):
        if url.endswith("/usercode"):
            return {"device_auth_id": "D1", "user_code": "WXYZ", "interval": 1, "expires_in": 100}
        if url.endswith("/deviceauth/token"):
            polls["n"] += 1
            if polls["n"] == 1:   # 403 pending COMO NA OPENAI (aninhado) — não pode abortar
                return oauth._err_payload(403, '{"error":{"code":"deviceauth_authorization_pending"}}')
            if polls["n"] == 2:   # slow_down namespaced → segue (e aumenta o intervalo)
                return oauth._err_payload(403, '{"error":{"code":"deviceauth_slow_down"}}')
            return {"authorization_code": "AC", "code_verifier": "CV"}
        return {}

    monkeypatch.setattr(oauth, "_post_json", fake_post_json)
    monkeypatch.setattr(oauth, "_post_form",
                        lambda url, fields: {"access_token": "AT", "refresh_token": "RT",
                                             "id_token": "h.y.s", "expires_in": 3600})
    clock = [1000.0]
    data = oauth.codex_device_login(
        lambda m: None, now=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s)
    )
    assert data["access_token"] == "AT" and polls["n"] == 3   # aguentou 2 "pending"/"slow_down" antes do code
    assert oauth.codex_access_token(now=lambda: clock[0]) == "AT"


def test_codex_device_login_still_raises_on_real_error(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(oauth, "_CLI_AUTH", tmp_path / "no_cli.json")

    def fake_post_json(url, payload):
        if url.endswith("/usercode"):
            return {"device_auth_id": "D1", "user_code": "WXYZ", "interval": 1, "expires_in": 100}
        return oauth._err_payload(400, '{"error":{"code":"expired_token"}}')   # erro REAL → aborta

    monkeypatch.setattr(oauth, "_post_json", fake_post_json)
    clock = [1000.0]
    import pytest
    with pytest.raises(RuntimeError):
        oauth.codex_device_login(lambda m: None, now=lambda: clock[0],
                                 sleep=lambda s: clock.__setitem__(0, clock[0] + s))


def test_generic_device_login_tolerates_namespaced_pending(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    seq = iter([
        {"device_code": "DC", "user_code": "U", "verification_uri": "https://x", "interval": 1, "expires_in": 50},
        oauth._err_payload(403, '{"error":{"code":"deviceauth_authorization_pending"}}'),
        {"access_token": "AT2", "refresh_token": "RT2", "expires_in": 3600},
    ])
    monkeypatch.setattr(oauth, "_post_form", lambda url, fields: next(seq))
    clock = [0.0]
    data = oauth.device_login("acme", {"client_id": "c", "device_authorization_url": "https://d",
                                       "token_url": "https://t"},
                              lambda m: None, now=lambda: clock[0],
                              sleep=lambda s: clock.__setitem__(0, clock[0] + s))
    assert data["access_token"] == "AT2"


def test_logout_removes_store_and_flags_cli_fallback(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    cli = tmp_path / "codex_auth.json"
    cli.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(oauth, "_CLI_AUTH", cli)
    oauth.save_tokens("codex", {"access_token": "x", "expires_at": 9_999_999_999})
    res = oauth.logout("codex")
    assert res["removed"] is True and res["cli_auth"] is True
    assert oauth.has_tokens("codex") is False
    # idempotente: segunda vez não tem mais o store, mas ainda flagga o CLI
    res2 = oauth.logout("codex")
    assert res2["removed"] is False and res2["cli_auth"] is True
