"""Estado de arquivo lido — base anti-stale (pesquisa #7, item 7).

Quando uma tool LÊ um arquivo, registra o mtime daquele instante. Antes de SOBRESCREVER, a
tool de escrita pergunta `check_stale`: se o arquivo mudou no disco depois da leitura (outro
processo, o dono, um editor), o agente é avisado em vez de apagar mudanças que nunca viu.

Tudo aqui é FAIL-OPEN: sem mtime gravado, ou com `stat` falhando, ele se cala (None) e NUNCA
levanta — não pode ser o motivo de uma escrita legítima falhar.
"""
from __future__ import annotations

from pathlib import Path

from okami.core.tools.base import ToolContext


def record_read(ctx: ToolContext, rel: str, path: Path) -> None:
    """Marca `rel` como lido e guarda o mtime do disco naquele instante (baseline do anti-stale).

    O rel entra em `read_files` sempre (grounding §3.7). O mtime é best-effort: se o `stat`
    falhar (arquivo sumiu numa race), pula o registro do mtime sem explodir."""
    ctx.read_files.add(rel)
    try:
        ctx.read_mtimes[rel] = path.stat().st_mtime
    except OSError:
        pass  # sem baseline → check_stale ficará fail-open (None) p/ esse rel


def check_stale(ctx: ToolContext, rel: str, path: Path) -> str | None:
    """Aviso (PT) se o arquivo mudou no disco DEPOIS da leitura; None se está tudo certo.

    None quando: não há mtime gravado p/ esse rel (nunca lido aqui → fail-open), o mtime está
    inalterado, ou o `stat` falha agora. Nunca levanta."""
    gravado = ctx.read_mtimes.get(rel)
    if gravado is None:
        return None  # sem baseline → não temos como saber; fail-open
    try:
        atual = path.stat().st_mtime
    except OSError:
        return None  # stat falhou → fail-open (não bloqueia a escrita)
    if atual == gravado:
        return None
    return (f"O arquivo '{rel}' mudou no disco depois que você o leu — alguém ou outro processo "
            "o editou. Leia de novo antes de sobrescrever para não apagar essas mudanças.")
