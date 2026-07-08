"""Cofre de segredos CIFRADO em repouso (okami/core/secretvault.py) — diretiva do dono "Só no cofre,
nunca no LLM": o valor NUNCA fica em texto plano no disco (diferente do `.env` global do
store_secret). Fernet + chave local-à-máquina em `$OKAMI_HOME/.secret_key` (0600), gerada no 1º uso.
"""
from __future__ import annotations

import json

from okami.core import secretvault as sv


def test_round_trip_encrypt_decrypt(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    sv.vault_set("GITHUB_TOKEN", "ghp_abcdef0123456789ABCDEF0123456789")  # pragma: allowlist secret
    assert sv.vault_get("GITHUB_TOKEN") == "ghp_abcdef0123456789ABCDEF0123456789"  # pragma: allowlist secret


def test_value_is_encrypted_at_rest_not_plaintext(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    secret = "ghp_topsecretvaluethatmustneverbeondiskplain"  # pragma: allowlist secret
    sv.vault_set("GITHUB_TOKEN", secret)
    raw = sv.vault_path().read_text(encoding="utf-8")
    assert secret not in raw                              # o VALOR cru não aparece no arquivo
    data = json.loads(raw)
    assert "GITHUB_TOKEN" in data                          # o NOME (não sensível) fica visível
    assert data["GITHUB_TOKEN"] != secret


def test_key_file_and_vault_file_are_0600(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    sv.vault_set("X_TOKEN", "some-value-1234567890")
    assert (sv.key_path().stat().st_mode & 0o777) == 0o600
    assert (sv.vault_path().stat().st_mode & 0o777) == 0o600


def test_vault_names_lists_names_not_values(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    sv.vault_set("A_TOKEN", "value-a-1234567890")
    sv.vault_set("B_TOKEN", "value-b-1234567890")
    names = sv.vault_names()
    assert names == ["A_TOKEN", "B_TOKEN"]
    assert "value-a-1234567890" not in names
    assert "value-b-1234567890" not in names


def test_vault_get_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    assert sv.vault_get("NOPE") is None


def test_vault_get_corrupted_file_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    sv.vault_set("A_TOKEN", "value-a-1234567890")
    sv.vault_path().write_text('{"A_TOKEN": "not-a-real-fernet-token"}', encoding="utf-8")
    assert sv.vault_get("A_TOKEN") is None                 # nunca levanta, nunca "adivinha"


def test_upsert_overwrites_previous_value(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    sv.vault_set("TOKEN_X", "v1-1234567890")
    sv.vault_set("TOKEN_X", "v2-1234567890")
    assert sv.vault_get("TOKEN_X") == "v2-1234567890"


def test_resolve_secret_prefers_vault_over_environ(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    monkeypatch.setenv("SOME_KEY", "from-env-file")
    sv.vault_set("SOME_KEY", "from-vault")
    assert sv.resolve_secret("SOME_KEY") == "from-vault"


def test_resolve_secret_falls_back_to_environ_when_absent_from_vault(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    monkeypatch.setenv("LEGACY_KEY", "from-dotenv")       # simula .env já carregado em os.environ
    assert sv.resolve_secret("LEGACY_KEY") == "from-dotenv"


def test_resolve_secret_absent_everywhere_is_none(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    monkeypatch.delenv("TOTALLY_MISSING_KEY", raising=False)
    assert sv.resolve_secret("TOTALLY_MISSING_KEY") is None


def test_apply_vault_to_environ_overrides_dotenv_value_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    monkeypatch.setenv("MINIMAX_API_KEY", "old-from-dotenv")
    sv.vault_set("MINIMAX_API_KEY", "fresh-from-vault")
    res = sv.apply_vault_to_environ()
    assert res["applied"] == 1
    import os
    assert os.environ["MINIMAX_API_KEY"] == "fresh-from-vault"


def test_apply_vault_to_environ_non_destructive_when_override_false(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    monkeypatch.setenv("MINIMAX_API_KEY", "old-from-dotenv")
    sv.vault_set("MINIMAX_API_KEY", "fresh-from-vault")
    res = sv.apply_vault_to_environ(override=False)
    assert res["skipped"] == 1
    import os
    assert os.environ["MINIMAX_API_KEY"] == "old-from-dotenv"


def test_apply_vault_to_environ_empty_vault_is_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    res = sv.apply_vault_to_environ()
    assert res == {"applied": 0, "skipped": 0, "error": ""}
    assert not sv.key_path().exists()                     # cofre vazio NUNCA gera a chave à toa
