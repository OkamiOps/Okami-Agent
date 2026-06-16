"""Preflight de CA bundle SSL (#11, port do Hermes agent/ssl_guard.py).

Pega path de CA bundle quebrado ANTES de o httpx/openai virar isso num `FileNotFoundError: [Errno 2]`
opaco lá na 1ª chamada HTTPS. Valida as env vars de CA bundle (existe + arquivo + carregável) e o
certifi empacotado. Erro acionável com dica de conserto. Desliga com OKAMI_SKIP_SSL_GUARD=1.
"""
from __future__ import annotations

import logging
import os
import ssl
from pathlib import Path

logger = logging.getLogger(__name__)

_CA_BUNDLE_ENV_VARS = ("OKAMI_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
_SKIP_VALUES = {"1", "true", "yes", "on"}


class SSLConfigError(RuntimeError):
    """CA bundle SSL mal configurado (path ausente/corrompido ou certifi inacessível)."""


def _skip_enabled() -> bool:
    return os.getenv("OKAMI_SKIP_SSL_GUARD", "").strip().lower() in _SKIP_VALUES


def _repair_hint() -> str:
    return ("Conserto: uv pip install --force-reinstall certifi httpx\n"
            "Se você configurou um CA bundle corporativo custom, conserte ou tire a env var quebrada.")


def _ssl_err(message: str) -> SSLConfigError:
    return SSLConfigError(f"{message}\n{_repair_hint()}")


def _validate_bundle_path(label: str, value: str, *, require_substantial: bool = False) -> None:
    path = Path(value).expanduser()
    if not path.exists():
        raise _ssl_err(f"{label} aponta p/ um CA bundle ausente: {value}")
    if not path.is_file():
        raise _ssl_err(f"{label} não aponta p/ um arquivo de CA bundle: {value}")
    if require_substantial and path.stat().st_size < 1024:
        raise _ssl_err(f"{label} em {value} parece corrompido (pequeno demais)")
    try:
        ctx = ssl.create_default_context(cafile=str(path))
    except Exception as exc:  # noqa: BLE001
        raise _ssl_err(f"{label} CA bundle em {value} não carrega: {exc}") from exc
    if not ctx.get_ca_certs():
        raise _ssl_err(f"{label} CA bundle em {value} não carregou nenhum certificado")


def verify_ca_bundle() -> None:
    """Verifica que os CA certs configurados e o certifi empacotado existem e carregam.

    Levanta SSLConfigError se uma env var de CA bundle aponta p/ path ruim, ou se o certifi
    empacotado está ausente/corrompido. Best-effort no boot — não é fatal se chamado em try/except."""
    if _skip_enabled():
        logger.debug("ssl_guard pulado via OKAMI_SKIP_SSL_GUARD")
        return
    for env_var in _CA_BUNDLE_ENV_VARS:
        value = os.getenv(env_var)
        if value:
            _validate_bundle_path(env_var, value)
    try:
        import certifi
    except Exception as exc:  # noqa: BLE001
        raise _ssl_err(f"certifi não importável: {exc}") from exc
    _validate_bundle_path("certifi", str(certifi.where()), require_substantial=True)


__all__ = ["SSLConfigError", "verify_ca_bundle"]
