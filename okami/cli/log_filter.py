"""Filtro multi-eixo p/ `okami logs` (#11, port do Hermes hermes_cli/subcommands/logs.py).

Operador precisa diagnosticar sem grepar 50MB: filtra por nível (INFO/WARNING/ERROR/DEBUG), componente
(gateway/agent/tools/cron…) e janela de tempo (--since 1h/30m/2d). Funções puras p/ testar; o comando
CLI só passa as linhas + flags.
"""
from __future__ import annotations

import re

_LEVELS = ("DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL")
_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})")


def parse_duration(s: str) -> int | None:
    """'30m'/'2h'/'1d'/'45s' → segundos, ou None se não parsear."""
    m = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", s or "", re.IGNORECASE)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def _line_epoch(line: str) -> float | None:
    """Epoch do timestamp ISO no início da linha, ou None se não houver/parsear."""
    m = _TS_RE.search(line)
    if not m:
        return None
    import datetime as _dt
    raw = m.group(1).replace(" ", "T")
    try:
        return _dt.datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


def filter_log_lines(lines, *, level: str = "", component: str = "", since: str = "", now: float | None = None):
    """Aplica os filtros (todos opcionais, AND). `level`: só linhas com nível >= o pedido (na verdade,
    contém o token de nível). `component`: substring. `since`: janela a partir de `now`."""
    out = list(lines)
    if level:
        lv = level.upper()
        out = [line for line in out if re.search(rf"\b{re.escape(lv)}\b", line)]
    if component:
        out = [line for line in out if component.lower() in line.lower()]
    if since:
        secs = parse_duration(since)
        if secs is not None and now is not None:
            cutoff = now - secs
            kept = []
            for line in out:
                e = _line_epoch(line)
                if e is None or e >= cutoff:          # sem timestamp → mantém (não some por engano)
                    kept.append(line)
            out = kept
    return out


__all__ = ["parse_duration", "filter_log_lines"]
