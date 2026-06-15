"""Proveniência por checksum — confere a integridade de binário baixado em runtime.

Quando o agente puxa uma ferramenta auxiliar da rede, executar o blob cru é cego: man-in-the-middle
ou mirror comprometido trocam o conteúdo sem aviso. Aqui o chamador compara o sha256 do arquivo
contra um valor esperado (fixado no código/config) ANTES de rodar. Tudo best-effort e fail-safe:
nunca levanta — devolve False/"" em qualquer pepino, pois "não consigo provar" == "não confio"."""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1 << 20  # 1 MiB por leitura — não carrega o binário inteiro na memória


def sha256_file(path) -> str:
    """sha256 hex (64 chars, minúsculo) do arquivo em `path`; "" se não der pra ler.

    Streama em blocos p/ aguentar binário grande sem estourar RAM."""
    try:
        h = hashlib.sha256()
        with Path(path).open("rb") as f:
            for bloco in iter(lambda: f.read(_CHUNK), b""):
                h.update(bloco)
        return h.hexdigest()
    except OSError:
        # arquivo sumiu/sem permissão/é diretório — sem hash, sem confiança
        return ""


def verify_checksum(path, expected: str) -> bool:
    """True só se o sha256 de `path` casar com `expected` (compara case-insensitive).

    False em arquivo inexistente, `expected` vazio/None ou hash diferente — fail-safe: a dúvida
    nunca vira um 'sim'."""
    if not expected or not isinstance(expected, str):
        return False
    atual = sha256_file(path)
    if not atual:                       # não conseguiu ler o arquivo → não confia
        return False
    return atual.lower() == expected.strip().lower()
