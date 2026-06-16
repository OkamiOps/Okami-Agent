"""Limites de tool-output config-driven (#11, port do Hermes tools/tool_output_limits.py).

Antes os caps viviam hardcoded em vários lugares (execute_code._MAX_OUTPUT=100k, remote=200k). Aqui
centralizamos atrás do bloco de config `tools.tool_output: {max_bytes, max_lines, max_line_length}`,
com fallback defensivo p/ o default embutido (config malformado NÃO quebra a tool)."""
from __future__ import annotations


def output_limit(cfg, key: str, default: int) -> int:
    """Lê `tools.tool_output[key]` do cfg (se int positivo), senão devolve `default`. Nunca levanta."""
    try:
        tools = getattr(cfg, "tools", None) or {}
        if not isinstance(tools, dict):
            tools = getattr(tools, "__dict__", {}) or {}
        block = tools.get("tool_output") or {}
        val = block.get(key)
        if isinstance(val, bool):                 # bool é int em Python — não conta como limite
            return default
        if isinstance(val, int) and val > 0:
            return val
    except Exception:  # noqa: BLE001 — config malformado → default
        pass
    return default


__all__ = ["output_limit"]
