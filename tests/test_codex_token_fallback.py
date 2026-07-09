"""Incidente 2026-07: store codex com token EXPIRADO e SEM refresh devolvia o token morto
em vez de cair no ~/.codex/auth.json válido → generate_image passava no check() mas 401."""
import json
from okami.llm import oauth


def test_store_morto_sem_refresh_cai_pro_cli(tmp_path, monkeypatch):
    # store: token expirado, sem refresh (o caso do arquivo-lixo "old-token")
    store = tmp_path / "codex.json"
    store.write_text(json.dumps({"access_token": "old-token", "expires_at": 1.0, "raw": {}}))
    monkeypatch.setattr(oauth, "load_tokens", lambda p: json.loads(store.read_text()))
    # CLI auth válido
    cli = tmp_path / "auth.json"
    cli.write_text(json.dumps({"tokens": {"access_token": "VALID-CLI-TOKEN", "refresh_token": ""}}))
    monkeypatch.setattr(oauth, "_CLI_AUTH", cli)
    tok = oauth.codex_access_token(now=lambda: 1000.0)
    assert tok == "VALID-CLI-TOKEN"     # NÃO "old-token"


def test_store_valido_ainda_vence(tmp_path, monkeypatch):
    store = tmp_path / "codex.json"
    store.write_text(json.dumps({"access_token": "FRESH", "expires_at": 9_999_999_999.0}))
    monkeypatch.setattr(oauth, "load_tokens", lambda p: json.loads(store.read_text()))
    monkeypatch.setattr(oauth, "_CLI_AUTH", tmp_path / "nope.json")
    assert oauth.codex_access_token(now=lambda: 1000.0) == "FRESH"
