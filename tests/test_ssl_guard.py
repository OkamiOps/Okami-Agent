"""#11 Onda 1: preflight de CA bundle SSL (port do Hermes agent/ssl_guard.py).

Pega path de CA bundle quebrado (env var apontando p/ arquivo ausente) ANTES do 1º HTTPS, com erro
acionável — em vez do FileNotFoundter opaco que httpx/openai cospem lá na frente.
"""
from __future__ import annotations

import pytest


def test_verify_raises_on_missing_bundle_env(monkeypatch, tmp_path):
    from okami.llm.ssl_guard import SSLConfigError, verify_ca_bundle
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "nao-existe.pem"))
    with pytest.raises(SSLConfigError) as e:
        verify_ca_bundle()
    assert "REQUESTS_CA_BUNDLE" in str(e.value) and "certifi" in str(e.value).lower()  # erro acionável


def test_verify_skips_when_disabled(monkeypatch, tmp_path):
    from okami.llm.ssl_guard import verify_ca_bundle
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "nao-existe.pem"))
    monkeypatch.setenv("OKAMI_SKIP_SSL_GUARD", "1")
    verify_ca_bundle()                       # skip → não levanta apesar do path ruim


def test_verify_passes_with_certifi(monkeypatch):
    from okami.llm.ssl_guard import verify_ca_bundle
    for v in ("OKAMI_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "OKAMI_SKIP_SSL_GUARD"):
        monkeypatch.delenv(v, raising=False)
    verify_ca_bundle()                       # certifi do venv carrega → sem erro


def test_verify_raises_on_corrupt_small_bundle(monkeypatch, tmp_path):
    from okami.llm.ssl_guard import SSLConfigError, verify_ca_bundle
    bad = tmp_path / "tiny.pem"
    bad.write_text("nope", encoding="utf-8")         # existe mas não é bundle válido
    monkeypatch.setenv("SSL_CERT_FILE", str(bad))
    with pytest.raises(SSLConfigError):
        verify_ca_bundle()
