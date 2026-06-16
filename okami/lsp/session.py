"""Pool LSP persistente em escopo de PROCESSO + delta de diagnostics MULTI-LINGUAGEM no write (#19).

Fecha o "ainda não wired no write" do #18: o write/edit de um arquivo NÃO-.py num repo git, com um
language server conhecido (gopls/ts/rust/bash/clangd), agora ganha o aviso de erro SEMÂNTICO NOVO — usando
o cliente persistente (server reusado entre edições). O .py segue no one-shot do pyright (já testado).

Fail-open total: sem git / sem server / sem binário / qualquer erro → "" (nunca bloqueia, nunca levanta).
"""
from __future__ import annotations

import atexit
from pathlib import Path

from okami.core.lsp.diagnostics import _error_keys
from okami.lsp.pool import LspPool
from okami.lsp.servers import server_for_path
from okami.lsp.workspace import find_git_worktree

_POOL: LspPool | None = None


def session_pool() -> LspPool:
    """Pool persistente do processo (lazy; shutdown no atexit)."""
    global _POOL
    if _POOL is None:
        _POOL = LspPool()
        atexit.register(_POOL.shutdown)
    return _POOL


def multi_lang_delta(workspace, rel: str, before: str, after: str, *, _pool: LspPool | None = None) -> str:
    """Aviso dos erros semânticos NOVOS num arquivo NÃO-.py (o .py é do pyright one-shot). "" se nada."""
    try:
        path = str(Path(workspace) / rel)
        if not find_git_worktree(path):                    # gate de git PRIMEIRO (barato vs scan de PATH)
            return ""                                      # fora de repo → nem toca no catálogo/PATH/pool
        srv = server_for_path(path)
        if srv is None or srv.id == "pyright":             # .py → tratado pelo one-shot existente
            return ""
        pool = _pool or session_pool()
        after_keys = _error_keys(pool.diagnose_path(workspace, rel, after) or [])
        if not after_keys:                                 # after limpo → nada a avisar
            return ""
        before_keys = _error_keys(pool.diagnose_path(workspace, rel, before or "") or [])
        novos = after_keys - before_keys
        if not novos:
            return ""
        partes = [sym or body for body, sym in sorted(novos)]
        return f"⚠ lsp: {rel}: {'; '.join(partes)} ({srv.id})"
    except Exception:  # noqa: BLE001 — fail-open total
        return ""


__all__ = ["session_pool", "multi_lang_delta"]
