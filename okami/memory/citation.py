"""Citação/origem de memória (P2 #11 self-review) — ao INJETAR memória, mostrar DE ONDE e QUÃO confiável.

Toda memória recuperada já carrega `kind` (categoria), `source` (agent/task/cli/honcho/learning…) e
`score` (relevância+recência+importância JÁ normalizadas em [0,1] no recall). Anexar isso ancora a
resposta na origem real e deixa o replay/UX auditável — sem o modelo recitar 'na memória consta'.
"""

from __future__ import annotations


def cite(item) -> str:
    """Tag compacta de origem: `[kind · source · 0.82]`. Omite a confiança se o score não for [0,1]
    (BM25 cru/None → não inventa número)."""
    kind = (getattr(item, "kind", "") or "?").strip() or "?"
    src = (getattr(item, "source", "") or "?").strip() or "?"
    score = getattr(item, "score", None)
    conf = f" · {score:.2f}" if isinstance(score, (int, float)) and 0.0 <= score <= 1.0 else ""
    return f"[{kind} · {src}{conf}]"


def cited_line(item, *, width: int = 200) -> str:
    """Linha `- <texto>  [origem]` usada na injeção e no recall."""
    text = (getattr(item, "text", "") or "").strip()[:width]
    return f"- {text}  {cite(item)}"
