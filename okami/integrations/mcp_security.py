"""Checagem de segurança de entradas de servidor MCP configuradas pelo dono (#11, port do Hermes
hermes_cli/mcp_security.py).

O transporte stdio do MCP suporta comando local arbitrário de propósito (o dono roda servidores
próprios). Isto NÃO tenta sandboxar isso — só marca a forma de exfiltração de ALTO sinal: um
interpretador de shell cujo script inline invoca ferramenta de egress de rede (curl/wget/nc/…).
"""
from __future__ import annotations

import os
import re
import shlex
from typing import Any

_SHELL_INTERPRETERS = frozenset({
    "bash", "sh", "zsh", "dash", "fish",
    "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
})

_EGRESS_PATTERN = re.compile(
    r"(?<![\w.-])(?:curl|wget|nc|ncat|socat)(?![\w.-])"
    r"|/dev/tcp/"
    r"|\bInvoke-WebRequest\b"
    r"|\bInvoke-RestMethod\b"
    r"|\bSystem\.Net\.WebClient\b",
    re.IGNORECASE,
)

_EXFIL_HINT_PATTERN = re.compile(
    r"\.env\b|--data-binary|--data-raw|\b-X\s+POST\b|\bPOST\b|<\s*[^\s]+",
    re.IGNORECASE,
)


def _command_basename(command: Any) -> str:
    text = str(command or "").strip()
    if not text:
        return ""
    try:
        parts = shlex.split(text, posix=(os.name != "nt"))
    except ValueError:
        parts = text.split()
    first = parts[0] if parts else text
    return os.path.basename(first).lower()


def _inline_script(args: Any) -> str:
    if args is None:
        return ""
    if isinstance(args, (list, tuple)):
        return " ".join(str(item) for item in args)
    return str(args)


def validate_mcp_server_entry(name: str, entry: dict[str, Any]) -> list[str]:
    """Avisos de segurança p/ uma entrada de servidor MCP. Lista vazia = não suspeito sob a heurística
    estreita de exfiltração (interpretador de shell + egress nos args). NÃO é whitelist: MCP local
    legítimo ainda pode usar comando custom, script Python, npx, uvx etc."""
    if not isinstance(entry, dict):
        return []
    basename = _command_basename(entry.get("command"))
    if basename not in _SHELL_INTERPRETERS:
        return []
    script = _inline_script(entry.get("args"))
    if not script or not _EGRESS_PATTERN.search(script):
        return []
    issue = f"MCP '{name}' usa interpretador de shell '{entry.get('command')}' com egress de rede nos args"
    if _EXFIL_HINT_PATTERN.search(script):
        issue += " e argumentos com forma de exfiltração"
    return [issue]


def is_mcp_server_entry_suspicious(name: str, entry: dict[str, Any]) -> bool:
    return bool(validate_mcp_server_entry(name, entry))


__all__ = ["validate_mcp_server_entry", "is_mcp_server_entry_suspicious"]
