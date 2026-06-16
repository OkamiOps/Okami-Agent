"""Formata diagnostics do LSP p/ a saída de tool (#17, port do Hermes agent/lsp/reporter.py).

O modelo vê um resumo compacto, filtrado por severidade e limitado por linha dos diagnostics introduzidos
pela última edição — blocos `<diagnostics>` com linha/coluna 1-indexadas. PURO/testável offline.
"""
from __future__ import annotations

from typing import Any, Dict, List

SEVERITY_NAMES = {1: "ERROR", 2: "WARN", 3: "INFO", 4: "HINT"}
DEFAULT_SEVERITIES = frozenset({1})                      # só ERROR por padrão (warn/info inundariam)

MAX_PER_FILE = 20
MAX_TOTAL_CHARS = 4000


def format_diagnostic(d: Dict[str, Any]) -> str:
    """Uma linha por diagnostic: `SEV [linha:col] mensagem [code] (source)` (1-indexado)."""
    sev = SEVERITY_NAMES.get(d.get("severity") or 1, "ERROR")
    rng = d.get("range") or {}
    start = rng.get("start") or {}
    line = int(start.get("line", 0)) + 1
    col = int(start.get("character", 0)) + 1
    msg = str(d.get("message") or "").rstrip()
    code = d.get("code")
    code_part = f" [{code}]" if code not in {None, ""} else ""
    source = d.get("source")
    source_part = f" ({source})" if source else ""
    return f"{sev} [{line}:{col}] {msg}{code_part}{source_part}"


def report_for_file(file_path: str, diagnostics: List[Dict[str, Any]], *,
                    severities: frozenset = DEFAULT_SEVERITIES, max_per_file: int = MAX_PER_FILE) -> str:
    """Bloco `<diagnostics file=...>` de um arquivo. String vazia se nada passa no filtro de severidade."""
    if not diagnostics:
        return ""
    filtered = [d for d in diagnostics if (d.get("severity") or 1) in severities]
    if not filtered:
        return ""
    limited = filtered[:max_per_file]
    extra = len(filtered) - len(limited)
    body = "\n".join(format_diagnostic(d) for d in limited)
    if extra > 0:
        body += f"\n... e mais {extra}"
    return f'<diagnostics file="{file_path}">\n{body}\n</diagnostics>'


def truncate(s: str, *, limit: int = MAX_TOTAL_CHARS) -> str:
    """Teto duro no resumo formatado."""
    if len(s) <= limit:
        return s
    marker = "\n…[truncado]"
    if limit <= len(marker):                         # limit minúsculo → só o marcador (evita fatia negativa)
        return marker
    return s[: limit - len(marker)] + marker


__all__ = ["SEVERITY_NAMES", "DEFAULT_SEVERITIES", "MAX_PER_FILE",
           "format_diagnostic", "report_for_file", "truncate"]
