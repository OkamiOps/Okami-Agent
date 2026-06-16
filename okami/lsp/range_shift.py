"""Mapa de deslocamento de linha diff-aware p/ filtro delta de diagnostics entre edições (#17, port do
Hermes agent/lsp/range_shift.py).

Quando uma edição insere/remove linhas, todo diagnostic ABAIXO do ponto de edição muda de número. O filtro
delta subtrai a baseline pré-edição dos diagnostics pós-edição por (severity,code,source,message,range) —
sem ajuste, um diagnostic deslocado mas idêntico parece NOVO e inunda o agente. A correção (mesmo truque do
git blame): mapa linear por-trechos de linha-pré → linha-pós via difflib, aplicado à baseline antes da
diferença de conjuntos. Linha numa região DELETADA → None (some da baseline). Tudo PURO/testável offline.
"""
from __future__ import annotations

import difflib
from typing import Any, Callable, Dict, List, Optional


def build_line_shift(pre_text: str, post_text: str) -> Callable[[int], Optional[int]]:
    """Função que mapeia número de linha pré-edição (0-indexado, formato LSP) → pós-edição, ou None se a
    linha foi deletada. Um get_opcodes() na frente; o closure é barato por chamada."""
    pre_lines = pre_text.splitlines() if pre_text else []
    post_lines = post_text.splitlines() if post_text else []

    if pre_lines == post_lines:                          # conteúdo idêntico → identidade
        return lambda line: line

    sm = difflib.SequenceMatcher(a=pre_lines, b=post_lines, autojunk=False)
    opcodes = sm.get_opcodes()

    def shift(line: int) -> Optional[int]:
        for tag, i1, i2, j1, j2 in opcodes:
            if i1 <= line < i2:
                if tag == "equal":
                    return line - i1 + j1
                if tag in ("delete", "replace"):         # linha sem contraparte pós → some
                    return None
                # 'insert' tem i1 == i2 → line < i2 nunca bate
            if line < i1:
                break
        return max(0, len(post_lines) - 1) if post_lines else None

    return shift


def shift_diagnostic_range(diag: Dict[str, Any],
                           shift: Callable[[int], Optional[int]]) -> Optional[Dict[str, Any]]:
    """Cópia de `diag` com o range de linha remapeado por `shift`. None se a start-line foi deletada
    (caller tira da baseline). Não muta o original."""
    rng = diag.get("range") or {}
    start = rng.get("start") or {}
    end = rng.get("end") or {}

    pre_start_line = int(start.get("line", 0))
    pre_end_line = int(end.get("line", pre_start_line))

    new_start_line = shift(pre_start_line)
    if new_start_line is None:
        return None

    new_end_line = shift(pre_end_line)
    if new_end_line is None:                             # diagnostic atravessou a deleção → colapsa no start
        new_end_line = new_start_line

    shifted = dict(diag)
    shifted["range"] = {
        "start": {"line": new_start_line, "character": int(start.get("character", 0))},
        "end": {"line": new_end_line, "character": int(end.get("character", 0))},
    }
    return shifted


def shift_baseline(baseline: List[Dict[str, Any]],
                   shift: Callable[[int], Optional[int]]) -> List[Dict[str, Any]]:
    """Aplica `shift` a cada diagnostic da baseline, descartando os deletados."""
    out: List[Dict[str, Any]] = []
    for d in baseline:
        if not isinstance(d, dict):
            continue
        shifted = shift_diagnostic_range(d, shift)
        if shifted is not None:
            out.append(shifted)
    return out


__all__ = ["build_line_shift", "shift_diagnostic_range", "shift_baseline"]
