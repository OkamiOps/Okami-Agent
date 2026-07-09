"""Testes do login GitHub Copilot (device flow + troca pelo token curto da API), sem rede."""

from __future__ import annotations

from okami.llm import oauth_copilot as oc


def _isolate(tmp_path, monkeypatch):
    from okami.llm import oauth
    monkeypatch.setattr(oauth, "STORE_DIR", tmp_path / "cred")
    oc._exchange_cache.clear()


def test_device_login_pending_then_success_saves_raw_token(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    seq = iter([
        {"device_code": "DC1", "user_code": "ABCD-1234", "verification_uri": oc.VERIFICATION_URI,
         "interval": 1, "expires_in": 60},
        {"error": "authorization_pending"},
        {"access_token": "gho_abc123", "token_type": "bearer", "scope": "read:user"},
    ])
    calls = []

    def fake_post_form(url, fields):
        calls.append((url, fields))
        return next(seq)

    monkeypatch.setattr(oc, "_post_form", fake_post_form)
    clock = [0.0]
    emitted = []
    data = oc.copilot_login(emitted.append, now=lambda: clock[0],
                            sleep=lambda s: clock.__setitem__(0, clock[0] + s))

    assert data["github_token"] == "gho_abc123"
    from okami.llm.oauth import load_tokens
    assert load_tokens("copilot")["github_token"] == "gho_abc123"
    assert any("ABCD-1234" in m for m in emitted)
    # 1a chamada é device/code, as seguintes são poll no access_token com client_id do VS Code
    assert calls[0][0] == oc.DEVICE_CODE_URL
    assert calls[0][1]["client_id"] == oc.CLIENT_ID
    assert calls[1][0] == oc.ACCESS_TOKEN_URL


def test_device_login_slow_down_then_success(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    seq = iter([
        {"device_code": "DC1", "user_code": "U", "verification_uri": "https://x", "interval": 1,
         "expires_in": 60},
        {"error": "slow_down"},
        {"access_token": "ghu_xyz"},
    ])
    monkeypatch.setattr(oc, "_post_form", lambda url, fields: next(seq))
    clock = [0.0]
    data = oc.copilot_login(lambda m: None, now=lambda: clock[0],
                            sleep=lambda s: clock.__setitem__(0, clock[0] + s))
    assert data["github_token"] == "ghu_xyz"


def test_device_login_raises_on_real_error(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    seq = iter([
        {"device_code": "DC1", "user_code": "U", "verification_uri": "https://x", "interval": 1,
         "expires_in": 60},
        {"error": "access_denied"},
    ])
    monkeypatch.setattr(oc, "_post_form", lambda url, fields: next(seq))
    clock = [0.0]
    import pytest
    with pytest.raises(RuntimeError):
        oc.copilot_login(lambda m: None, now=lambda: clock[0],
                         sleep=lambda s: clock.__setitem__(0, clock[0] + s))


def test_classic_pat_is_rejected(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(oc, "load_tokens", lambda provider: {"github_token": "ghp_classicpat"})
    monkeypatch.setattr(oc, "_gh_cli_token", lambda: None)
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert oc._raw_github_token() is None


def test_raw_token_prefers_store_over_env_and_cli(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(oc, "load_tokens", lambda provider: {"github_token": "gho_store"})
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "gho_env")
    monkeypatch.setattr(oc, "_gh_cli_token", lambda: "gho_cli")
    assert oc._raw_github_token() == "gho_store"


def test_raw_token_falls_back_to_env_priority(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(oc, "load_tokens", lambda provider: None)
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "gho_ghtoken")
    monkeypatch.setenv("GITHUB_TOKEN", "gho_githubtoken")
    monkeypatch.setattr(oc, "_gh_cli_token", lambda: None)
    assert oc._raw_github_token() == "gho_ghtoken"


def test_raw_token_falls_back_to_gh_cli(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(oc, "load_tokens", lambda provider: None)
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(oc, "_gh_cli_token", lambda: "ghu_fromcli")
    assert oc._raw_github_token() == "ghu_fromcli"


def test_gh_cli_token_uses_subprocess(monkeypatch):
    class FakeResult:
        stdout = "gho_subprocess\n"

    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return FakeResult()

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    assert oc._gh_cli_token() == "gho_subprocess"
    assert calls["cmd"] == ["gh", "auth", "token"]


def test_gh_cli_token_fail_safe_when_gh_absent(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("gh not found")

    monkeypatch.setattr(oc.subprocess, "run", fake_run)
    assert oc._gh_cli_token() is None


def test_exchange_sends_special_headers_and_parses_response(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return oc.json.dumps({
                "token": "tgp_shortlived",
                "expires_at": 1_000_000,
                "endpoints": {"api": "https://enterprise.example.com/copilot"},
            }).encode("utf-8")

    def fake_urlopen(req, timeout=30):
        captured["url"] = req.full_url
        captured["headers"] = {k: v for k, v in req.header_items()}
        return FakeResponse()

    monkeypatch.setattr(oc.urllib.request, "urlopen", fake_urlopen)
    result = oc._exchange("gho_raw", now=500.0)

    assert captured["url"] == oc.EXCHANGE_URL
    assert captured["headers"]["Authorization"] == "token gho_raw"
    assert captured["headers"]["Editor-version"] == oc.EDITOR_VERSION
    assert captured["headers"]["User-agent"] == oc.USER_AGENT
    assert result["token"] == "tgp_shortlived"
    assert result["expires_at"] == 1_000_000
    assert result["base_url"] == "https://enterprise.example.com/copilot"


def test_copilot_access_token_full_flow_and_cache_reuse(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(oc, "_raw_github_token", lambda: "gho_raw")
    exchange_calls = {"n": 0}

    def fake_exchange(raw_token, now):
        exchange_calls["n"] += 1
        result = {"token": "tgp_1", "expires_at": now + 600, "base_url": oc.DEFAULT_BASE_URL,
                  "_fetched_at": now}
        oc._exchange_cache.update(result)
        return result

    monkeypatch.setattr(oc, "_exchange", fake_exchange)

    clock = [0.0]
    tok, base = oc.copilot_access_token(now=lambda: clock[0])
    assert tok == "tgp_1" and base == oc.DEFAULT_BASE_URL
    assert exchange_calls["n"] == 1

    # dentro da margem (120s) do expires_at (600s à frente) → reusa o cache, não troca de novo
    clock[0] = 400.0
    tok2, base2 = oc.copilot_access_token(now=lambda: clock[0])
    assert tok2 == "tgp_1"
    assert exchange_calls["n"] == 1

    # passou da margem → troca de novo
    clock[0] = 550.0
    oc.copilot_access_token(now=lambda: clock[0])
    assert exchange_calls["n"] == 2


def test_copilot_access_token_no_raw_token_returns_none(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(oc, "_raw_github_token", lambda: None)
    tok, base = oc.copilot_access_token(now=lambda: 0.0)
    assert tok is None and base is None


def test_copilot_base_url_default_when_no_cache(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert oc.copilot_base_url() == oc.DEFAULT_BASE_URL


def test_copilot_base_url_reflects_last_exchange(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    oc._exchange_cache.update({"base_url": "https://enterprise.example.com/copilot"})
    assert oc.copilot_base_url() == "https://enterprise.example.com/copilot"
