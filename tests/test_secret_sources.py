"""Secret sources plugável (pesquisa #6 item 19, paridade Hermes secret_sources/bitwarden).

Abstração de FONTE de segredo que injeta env-vars no boot DEPOIS do .env: não-destrutiva (só seta o
que falta), FAIL-NEVER-BLOCK (erro → 1 aviso, segue com o que o .env tinha). Bitwarden Secrets
Manager via `bws`: só BWS_ACCESS_TOKEN no ambiente; resto vem do cofre. Fetch injetável p/ teste.
"""
from __future__ import annotations

import os

from okami.core import secret_sources as ss


def test_apply_sets_missing_only(monkeypatch):
    monkeypatch.delenv("OKAMI_TEST_NEW", raising=False)
    monkeypatch.setenv("OKAMI_TEST_EXISTING", "do_env")
    fetched = {"OKAMI_TEST_NEW": "do_cofre", "OKAMI_TEST_EXISTING": "do_cofre"}
    res = ss.apply_secrets(fetch=lambda: fetched)
    assert os.environ["OKAMI_TEST_NEW"] == "do_cofre"        # faltava → setou
    assert os.environ["OKAMI_TEST_EXISTING"] == "do_env"     # já tinha (.env vence) → NÃO sobrescreve
    assert res["applied"] == 1


def test_apply_fail_never_blocks(monkeypatch):
    def boom():
        raise RuntimeError("bws offline")
    res = ss.apply_secrets(fetch=boom)
    assert res["applied"] == 0 and res["error"]              # erro vira resultado, não exceção


def test_apply_no_source_is_noop():
    res = ss.apply_secrets(fetch=lambda: {})
    assert res["applied"] == 0 and not res.get("error")


def test_bitwarden_disabled_without_token(monkeypatch):
    monkeypatch.delenv("BWS_ACCESS_TOKEN", raising=False)
    assert ss.bitwarden_available() is False


def test_bitwarden_enabled_with_token(monkeypatch):
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "tok")
    assert ss.bitwarden_available() is True


def test_parse_bws_output():
    raw = '[{"key": "OPENAI_API_KEY", "value": "sk-abc"}, {"key": "X", "value": "1"}]'
    parsed = ss.parse_bws_secrets(raw)
    assert parsed == {"OPENAI_API_KEY": "sk-abc", "X": "1"}


def test_parse_bws_bad_json():
    assert ss.parse_bws_secrets("not json") == {}


def test_apply_only_overrides_when_asked(monkeypatch):
    monkeypatch.setenv("OKAMI_TEST_OV", "do_env")
    res = ss.apply_secrets(fetch=lambda: {"OKAMI_TEST_OV": "do_cofre"}, override=True)
    assert os.environ["OKAMI_TEST_OV"] == "do_cofre" and res["applied"] == 1
