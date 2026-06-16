"""Detecção de silêncio INTENCIONAL (#11, port do Hermes gateway/response_filters.py).

O agente pode emitir um marcador exato p/ DELIBERADAMENTE não responder (≠ resposta vazia por erro):
NO_REPLY / SILENT / [SILENT] / NO REPLY. Reconhece as 4 formas canônicas com whitespace normalizado e
um teto de tamanho (um marcador é curto; texto longo que começa com 'SILENT' é resposta real).
"""
from __future__ import annotations

import re

_SILENT_MARKERS = frozenset({"no_reply", "silent", "no reply"})
_MAX_LEN = 64
_STRIP_RE = re.compile(r"^\s*\[?\s*(no[_\s]?reply|silent)\b\s*\]?\s*", re.IGNORECASE)  # \b: 'SILENT2' não casa


def _canonical(text: str) -> str:
    """Normaliza p/ comparação: minúsculas, sem colchetes, whitespace colapsado."""
    t = (text or "").strip().lower()
    if t.startswith("[") and t.endswith("]"):
        t = t[1:-1].strip()
    return " ".join(t.split())


def is_intentional_silence(text: str) -> bool:
    """True se `text` é (só) um marcador de silêncio. Texto substantivo NUNCA é silêncio."""
    if not text:
        return False
    if len(text.strip()) > _MAX_LEN:
        return False
    return _canonical(text) in _SILENT_MARKERS


def strip_silence_prefix(text: str) -> str:
    """Remove um prefixo de marcador de silêncio (p/ casos '[SILENT] nota interna' → 'nota interna')."""
    return _STRIP_RE.sub("", text or "").strip()


__all__ = ["is_intentional_silence", "strip_silence_prefix"]
