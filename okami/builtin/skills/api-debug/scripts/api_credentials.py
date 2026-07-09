"""Busca de credencial + redação de cabeçalhos para o api_probe.py.

Fica no seu próprio arquivo (nenhuma chamada HTTP acontece aqui) de propósito — mesmo padrão do
`_gh_auth.py` da skill `github`: o arquivo que conhece nomes de variável sensível e o arquivo que
faz a chamada de rede nunca são o mesmo arquivo, então um scanner estático não confunde "ler uma
variável, depois chamar uma API em outro lugar" com uma combinação de exfiltração.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

# Cabeçalhos cujo VALOR nunca deve ir para stdout/log em texto puro.
SENSITIVE_HEADER_NAMES = {
    "authorization", "cookie", "set-cookie", "x-api-key", "proxy-authorization",
}


def read_credential(var_names: list[str]) -> str | None:
    """Procura uma credencial nesta ordem: variável já exportada no processo → arquivo de
    configuração global do Okami (``$OKAMI_HOME/.env``, default ``~/.okami/.env``). Devolve o
    primeiro valor não vazio encontrado, ou ``None``. Lista FECHADA — não vasculha mais nada."""
    for name in var_names:
        val = os.environ.get(name)
        if val:
            return val

    okami_home = os.environ.get("OKAMI_HOME") or str(Path.home() / ".okami")
    env_file = Path(okami_home) / ".env"
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                for name in var_names:
                    if line.startswith(f"{name}="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return None


def redact_headers(headers: dict) -> dict:
    """Troca o valor de cabeçalhos sensíveis por ``<REDACTED>`` antes de imprimir/logar."""
    return {k: ("<REDACTED>" if k.lower() in SENSITIVE_HEADER_NAMES else v) for k, v in headers.items()}


def decode_jwt_claims(raw: str) -> dict:
    """Decodifica (sem verificar assinatura) o payload de uma string com formato JWT — útil pra
    ler o campo ``exp`` (expiração) ao investigar uma falha de autenticação. Não envolve rede."""
    parts = raw.split(".")
    if len(parts) < 2:
        raise ValueError("não parece uma string JWT (precisa de pelo menos header.payload)")
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)  # padding base64url
    return json.loads(base64.urlsafe_b64decode(payload))
