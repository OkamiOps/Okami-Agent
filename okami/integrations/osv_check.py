"""OSV malware-check p/ pacotes de servidor MCP (#11, port do Hermes tools/osv_check.py).

Antes de lançar um servidor MCP via npx/uvx, consulta a API OSV (Open Source Vulnerabilities) por
advisory de MALWARE (id MAL-*). CVE comum é ignorado — só malware confirmado bloqueia. A API é
gratuita, pública (Google), ~300ms. FAIL-OPEN: erro de rede/timeout/parse → permite (None).
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request

logger = logging.getLogger(__name__)

_OSV_ENDPOINT = os.getenv("OSV_ENDPOINT", "https://api.osv.dev/v1/query")
_TIMEOUT = 10


def check_package_for_malware(command: str, args: list) -> str | None:
    """Mensagem de erro se o pacote MCP tem advisory de malware, ou None (limpo/desconhecido).
    None (permite) p/ comando não-npx/uvx ou erro de rede."""
    ecosystem = _infer_ecosystem(command)
    if not ecosystem:
        return None
    package, version = _parse_package_from_args(args, ecosystem)
    if not package:
        return None
    try:
        malware = _query_osv(package, ecosystem, version)
    except Exception as exc:  # noqa: BLE001 — fail-open: rede/timeout/parse → permite
        logger.debug("OSV check falhou p/ %s/%s (permitindo): %s", ecosystem, package, exc)
        return None
    if malware:
        ids = ", ".join(m["id"] for m in malware[:3])
        summaries = "; ".join(m.get("summary", m["id"])[:100] for m in malware[:3])
        return (f"BLOQUEADO: pacote '{package}' ({ecosystem}) tem advisory de malware conhecido: "
                f"{ids}. Detalhes: {summaries}")
    return None


def _infer_ecosystem(command: str) -> str | None:
    base = os.path.basename(str(command or "")).lower()
    if base in {"npx", "npx.cmd"}:
        return "npm"
    if base in {"uvx", "uvx.cmd", "pipx"}:
        return "PyPI"
    return None


def _parse_package_from_args(args: list, ecosystem: str) -> tuple[str | None, str | None]:
    """Extrai (pacote, versão) dos args, ou (None, None). Honra --package=NAME / --package NAME / -p NAME
    (alvo explícito de instalação, distinto do binário executado)."""
    if not args:
        return None, None
    package_token = None
    take_next = False
    for arg in args:
        if not isinstance(arg, str):
            continue
        if take_next:
            package_token = arg
            break
        if arg in ("--package", "-p"):
            take_next = True
            continue
        if arg.startswith("--package="):
            package_token = arg[len("--package="):]
            break
        if arg.startswith("-"):
            continue
        package_token = arg
        break
    if not package_token:
        return None, None
    if ecosystem == "npm":
        return _parse_npm_package(package_token)
    if ecosystem == "PyPI":
        return _parse_pypi_package(package_token)
    return package_token, None


def _parse_npm_package(token: str) -> tuple[str | None, str | None]:
    """@scope/name@version ou name@version."""
    if token.startswith("@"):
        match = re.match(r"^(@[^/]+/[^@]+)(?:@(.+))?$", token)
        if match:
            return match.group(1), match.group(2)
        return token, None
    if "@" in token:
        parts = token.rsplit("@", 1)
        name = parts[0]
        version = parts[1] if len(parts) > 1 and parts[1] != "latest" else None
        return name, version
    return token, None


def _parse_pypi_package(token: str) -> tuple[str | None, str | None]:
    """name==version ou name[extras]==version."""
    match = re.match(r"^([a-zA-Z0-9._-]+)(?:\[[^\]]*\])?(?:==(.+))?$", token)
    if match:
        return match.group(1), match.group(2)
    return token, None


def _query_osv(package: str, ecosystem: str, version: str | None = None) -> list:
    """Consulta a API OSV por advisory MAL-*. Retorna a lista de vulns de malware."""
    payload: dict = {"package": {"name": package, "ecosystem": ecosystem}}
    if version:
        payload["version"] = version
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 — endpoint HTTPS fixo (api.osv.dev), payload controlado
        _OSV_ENDPOINT, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "okami-agent-osv-check/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
        result = json.loads(resp.read())
    return [v for v in result.get("vulns", []) if v.get("id", "").startswith("MAL-")]


__all__ = ["check_package_for_malware"]
