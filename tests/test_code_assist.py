"""#17 Google Code Assist (tier grátis Gemini via cloudcode-pa) — peças PURAS testáveis offline."""
from __future__ import annotations

from types import SimpleNamespace


# ── envelope da control-plane (wrap/unwrap) ──
def test_wrap_code_assist_request():
    from okami.llm.code_assist import wrap_code_assist_request
    inner = {"contents": [{"role": "user", "parts": [{"text": "oi"}]}]}
    env = wrap_code_assist_request(project_id="proj-1", model="gemini-2.5-flash", inner_request=inner,
                                   user_prompt_id="u1")
    assert env["project"] == "proj-1" and env["model"] == "gemini-2.5-flash"
    assert env["request"] == inner and env["user_prompt_id"] == "u1"


def test_unwrap_code_assist_response():
    from okami.llm.code_assist import unwrap_code_assist_response
    inner = {"candidates": [{"content": {"parts": [{"text": "pong"}]}}]}
    assert unwrap_code_assist_response({"response": inner}) == inner   # desembrulha o envelope
    assert unwrap_code_assist_response(inner) == inner                # já desembrulhado → passa


# ── refresh-token empacotado (refresh|project|managed) ──
def test_refresh_parts_roundtrip():
    from okami.llm.code_assist import RefreshParts
    rp = RefreshParts.parse("TOK|proj|managed")
    assert rp.refresh_token == "TOK" and rp.project_id == "proj" and rp.managed_project_id == "managed"
    assert RefreshParts.parse(rp.format()).refresh_token == "TOK"
    bare = RefreshParts.parse("SOTOKEN")                  # sem pipes → só o token
    assert bare.refresh_token == "SOTOKEN" and bare.project_id == ""


# ── PKCE (S256) ──
def test_generate_pkce_pair_is_s256():
    import base64
    import hashlib

    from okami.llm.code_assist import generate_pkce_pair
    verifier, challenge = generate_pkce_pair()
    assert len(verifier) >= 43
    expect = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expect


def test_build_auth_url_has_pkce_and_scopes():
    from okami.llm.code_assist import OAUTH_SCOPES, build_auth_url
    url = build_auth_url(client_id="cid", redirect_uri="http://127.0.0.1:8085/cb",
                         state="st", challenge="ch")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "code_challenge=ch" in url and "code_challenge_method=S256" in url
    assert "client_id=cid" in url and "access_type=offline" in url
    assert OAUTH_SCOPES.split()[0].replace(":", "%3A") in url or "scope=" in url


# ── completion via cloudcode (reusa a tradução do gemini_native; rede injetada) ──
def test_code_assist_complete_translates_and_unwraps():
    from okami.llm.code_assist import code_assist_complete
    pc = SimpleNamespace(name="gca", model="gemini-2.5-flash", project_id="proj")
    captured = {}

    def _post(url, body, token):
        captured["url"] = url
        captured["body"] = body
        captured["token"] = token
        return {"response": {"candidates": [{"content": {"parts": [{"text": "pong"}]},
                                             "finishReason": "STOP"}],
                             "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1}}}

    comp = code_assist_complete(pc, [{"role": "user", "content": "ping"}], None,
                                _token=lambda: "ACCESS", _post=_post)
    assert comp.text == "pong"
    assert "cloudcode-pa.googleapis.com" in captured["url"]
    assert captured["token"] == "ACCESS"
    assert captured["body"]["project"] == "proj"          # envelope com o project


def test_code_assist_complete_honors_request_timeout_override():
    from okami.llm.code_assist import code_assist_complete
    pc = SimpleNamespace(name="gca", model="gemini-2.5-flash", project_id="proj")
    captured = {}

    def _post(url, body, token, *, timeout):
        captured["timeout"] = timeout
        return {"response": {"candidates": [{"content": {"parts": [{"text": "pong"}]},
                                                   "finishReason": "STOP"}]}}

    code_assist_complete(pc, [{"role": "user", "content": "ping"}], None,
                         overrides={"timeout": 1.25}, _token=lambda: "ACCESS", _post=_post)
    assert captured["timeout"] == 1.25


def test_code_assist_complete_without_token_raises_clear():
    import pytest

    from okami.llm.code_assist import code_assist_complete
    pc = SimpleNamespace(name="gca", model="m", project_id="")

    def _token():
        raise RuntimeError("sem credencial Google — rode `okami gemini login`")

    with pytest.raises(RuntimeError, match="credencial"):
        code_assist_complete(pc, [{"role": "user", "content": "x"}], None, _token=_token, _post=lambda *a: {})


# ── quota buckets ──
def test_parse_quota_buckets():
    from okami.llm.code_assist import parse_quota_buckets
    resp = {"buckets": [{"modelId": "gemini-2.5-pro", "remainingFraction": 0.5, "resetTime": "2026-06-17"}]}
    rows = parse_quota_buckets(resp)
    assert rows and rows[0]["model_id"] == "gemini-2.5-pro" and rows[0]["remaining_fraction"] == 0.5


# ── OAuth: troca de code, persistência 0600 e refresh ──
def test_exchange_code_posts_authorization_code():
    from okami.llm.code_assist import exchange_code
    sent = {}

    def _post(url, form):
        sent["url"] = url
        sent["form"] = form
        return {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}

    tok = exchange_code("CODE", "VERIFIER", redirect_uri="http://127.0.0.1:8085/cb", _post=_post)
    assert tok["access_token"] == "AT"
    assert sent["form"]["grant_type"] == "authorization_code"
    assert sent["form"]["code"] == "CODE" and sent["form"]["code_verifier"] == "VERIFIER"
    assert "oauth2.googleapis.com/token" in sent["url"]


def test_save_and_load_credentials_0600(tmp_path, monkeypatch):
    import os

    from okami.llm import code_assist as ca
    monkeypatch.setattr(ca, "credentials_path", lambda: tmp_path / "google_oauth.json")
    ca.save_credentials({"access_token": "AT", "refresh_token": "RT", "expires_at": 9999999999})
    assert (tmp_path / "google_oauth.json").exists()
    mode = os.stat(tmp_path / "google_oauth.json").st_mode & 0o777
    assert mode == 0o600                                   # credencial NÃO legível por outros
    assert ca.load_credentials()["access_token"] == "AT"


def test_get_access_token_refreshes_when_expired(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from okami.llm import code_assist as ca
    monkeypatch.setattr(ca, "credentials_path", lambda: tmp_path / "google_oauth.json")
    ca.save_credentials({"access_token": "OLD", "refresh_token": "RT", "expires_at": 0})   # já expirou
    monkeypatch.setattr(ca, "refresh_access_token",
                        lambda rt, _post=None: {"access_token": "NEW", "expires_in": 3600})
    tok = ca._get_access_token(SimpleNamespace(name="gca"))
    assert tok == "NEW"                                     # expirado → renova
    assert ca.load_credentials()["access_token"] == "NEW"  # persiste o novo


def test_get_access_token_without_creds_raises(tmp_path, monkeypatch):
    import pytest

    from types import SimpleNamespace

    from okami.llm import code_assist as ca
    monkeypatch.setattr(ca, "credentials_path", lambda: tmp_path / "nope.json")
    with pytest.raises(RuntimeError, match="credencial"):
        ca._get_access_token(SimpleNamespace(name="gca"))


# ── transporte gemini_cloudcode roteia pelo dispatch ──
def test_dispatch_routes_gemini_cloudcode(monkeypatch):
    from okami.llm import transports
    pc = SimpleNamespace(transport="gemini_cloudcode", name="gca", model="m", project_id="")
    monkeypatch.setattr("okami.llm.code_assist.code_assist_complete",
                        lambda pc, msgs, model, ov=None: SimpleNamespace(text="ROTEOU"))
    out = transports.dispatch(pc, [{"role": "user", "content": "x"}], None)
    assert out.text == "ROTEOU"


# ── CLI `okami gemini login` imprime a URL de auth com PKCE ──
def test_cli_gemini_login_prints_auth_url():
    from typer.testing import CliRunner

    from okami.cli import app
    res = CliRunner().invoke(app, ["gemini", "login", "--print-url"])
    assert res.exit_code == 0
    assert "accounts.google.com/o/oauth2" in res.stdout and "code_challenge_method=S256" in res.stdout
