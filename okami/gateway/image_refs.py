"""Auto-extração de referências de imagem do TEXTO do usuário (#11, port do Hermes
agent/image_routing.extract_image_refs).

Deixa o usuário escrever 'olha ~/screenshot.png' ou 'confere https://x.com/a.png' inline, sem mecânica
de anexo explícito. Pula conteúdo dentro de bloco de código (``` ... ```) — caminho citado em exemplo
de código não é pedido de visão.
"""
from __future__ import annotations

import re

_EXT = r"(?:png|jpe?g|gif|webp|bmp|heic|heif)"
_LOCAL_RE = re.compile(r"(?<!\w)((?:~|\.{0,2})?/[^\s'\"`<>|]+?\." + _EXT + r")\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s'\"`<>]+?\." + _EXT + r"(?:\?[^\s'\"`<>]*)?", re.IGNORECASE)
_FENCE_RE = re.compile(r"```.*?```|`[^`]*`", re.DOTALL)


def extract_image_refs(text: str) -> tuple[list[str], list[str]]:
    """Devolve (caminhos_locais, urls) de imagem citados em `text`, fora de bloco de código. Dedup,
    ordem preservada."""
    if not text:
        return [], []
    stripped = _FENCE_RE.sub(" ", text)          # remove code-block/inline-code antes de varrer
    paths: list[str] = []
    for m in _LOCAL_RE.finditer(stripped):
        p = m.group(1)
        if p not in paths:
            paths.append(p)
    urls: list[str] = []
    for m in _URL_RE.finditer(stripped):
        u = m.group(0)
        if u not in urls:
            urls.append(u)
    return paths, urls


__all__ = ["extract_image_refs"]
