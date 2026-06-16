"""Re-alinhamento de tabela markdown ciente de largura de exibição (#11, port do Hermes
agent/markdown_tables.py — sem a dep wcwidth, usando unicodedata).

Caractere multi-byte (CJK, fullwidth) renderiza em 2 COLUNAS no terminal, mas o modelo padeia contando
1 → a tabela sai torta. Aqui recalculamos a largura de cada coluna por largura de EXIBIÇÃO e repadeamos,
preservando os pipes. Pega a deriva CJK/JP/CN sem dependência externa.
"""
from __future__ import annotations

import re
import unicodedata

_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def display_width(s: str) -> int:
    """Largura de EXIBIÇÃO de `s`: CJK/fullwidth = 2, combining = 0, resto = 1."""
    w = 0
    for ch in s:
        if unicodedata.category(ch) in ("Mn", "Me"):     # combining → não ocupa coluna
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def _pad(cell: str, width: int) -> str:
    return cell + " " * max(0, width - display_width(cell))


_CELL_SPLIT = re.compile(r"(?<!\\)\|")    # pipe NÃO escapado (\| é literal dentro da célula)


def _split_cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [c.strip() for c in _CELL_SPLIT.split(inner)]


def _realign_block(rows: list[str]) -> list[str]:
    parsed = [_split_cells(r) for r in rows]
    ncol = max(len(p) for p in parsed)
    for p in parsed:
        p += [""] * (ncol - len(p))                      # normaliza nº de colunas
    widths = [3] * ncol                                   # mín. 3 (markdown exige ≥3 dashes no separador)
    for i, p in enumerate(parsed):
        if _SEP_RE.match(rows[i]):                        # separador não conta p/ largura
            continue
        for c in range(ncol):
            widths[c] = max(widths[c], display_width(p[c]))
    out = []
    for i, p in enumerate(parsed):
        if _SEP_RE.match(rows[i]):
            cells = ["-" * widths[c] for c in range(ncol)]
        else:
            cells = [_pad(p[c], widths[c]) for c in range(ncol)]
        out.append("| " + " | ".join(cells) + " |")
    return out


def realign_markdown_tables(text: str) -> str:
    """Re-alinha cada bloco de tabela markdown em `text` (linhas consecutivas que começam com `|`)."""
    if "|" not in (text or ""):
        return text
    lines = text.splitlines()
    out: list[str] = []
    block: list[str] = []
    for line in lines:
        if _ROW_RE.match(line):
            block.append(line)
        else:
            if block:
                out.extend(_realign_block(block))
                block = []
            out.append(line)
    if block:
        out.extend(_realign_block(block))
    return "\n".join(out)


__all__ = ["display_width", "realign_markdown_tables"]
