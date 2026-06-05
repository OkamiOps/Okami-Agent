"""Resolução de referências `${VAR}` / `$VAR` a partir do ambiente.

Segredo não vai em texto no YAML versionado — vai como `${HONCHO_API_KEY}` (ou `api_key_env: NOME`)
e é resolvido AQUI, na hora de usar (Honcho base_url/api_key, headers/env de MCP…). Antes, o valor
literal `${HONCHO_API_KEY}` vazava como string pro SDK/servidor. Variável indefinida → string vazia
(= "não setado"), nunca o literal `${...}`.
"""

from __future__ import annotations

import os
import re

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def resolve_env(value):
    """Expande ${VAR}/$VAR de uma STRING via os.environ. Não-string passa intacto; indefinido → ''."""
    if not isinstance(value, str):
        return value
    return _ENV_REF.sub(lambda m: os.environ.get(m.group(1) or m.group(2), ""), value)


def resolve_env_map(d: dict | None) -> dict:
    """Aplica resolve_env nos VALORES string de um dict (ex.: headers/env de MCP)."""
    return {k: resolve_env(v) for k, v in (d or {}).items()}
