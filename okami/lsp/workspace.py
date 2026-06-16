"""Resolução de raiz de workspace p/ o LSP (#17, port do Hermes agent/lsp/workspace.py).

O LSP só ATIVA quando o arquivo/cwd está dentro de um repositório git — evita subir daemons de language
server p/ quem está na home (ex.: sessão de gateway). Per-server, cada servidor resolve a própria raiz
(pyproject.toml p/ Python, Cargo.toml p/ Rust…). Tudo PURO (só walk de filesystem), testável offline.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

_MAX_WALK = 64                                            # cap anti-symlink patológico


def normalize_path(p: str) -> str:
    return os.path.normpath(os.path.abspath(os.path.expanduser(p)))


def find_git_worktree(start: str) -> Optional[str]:
    """Sobe a partir de `start` procurando `.git` (dir OU arquivo, p/ worktrees). Devolve a raiz do
    worktree ou None. Cap de 64 níveis."""
    try:
        cur = Path(normalize_path(start))
    except (OSError, ValueError):
        return None
    if cur.is_file():
        cur = cur.parent
    for _ in range(_MAX_WALK):
        try:
            if (cur / ".git").exists():
                return str(cur)
        except OSError:
            return None
        parent = cur.parent
        if parent == cur:                                # chegou na raiz do FS
            return None
        cur = parent
    return None


def is_inside_workspace(path: str, workspace_root: str) -> bool:
    """`path` está contido em `workspace_root`? (contençao de caminho normalizada)."""
    try:
        p = Path(normalize_path(path))
        root = Path(normalize_path(workspace_root))
    except (OSError, ValueError):
        return False
    return root == p or root in p.parents


def nearest_root(start: str, markers: Iterable[str], *, excludes: Optional[Iterable[str]] = None,
                 ceiling: Optional[str] = None) -> Optional[str]:
    """Sobe de `start` procurando QUALQUER um dos `markers`. Devolve o diretório que contém o 1º marcador,
    ou None. Se um `excludes` casa ANTES, devolve None (servidor gateado-off p/ aquele arquivo)."""
    try:
        start_path = Path(normalize_path(start))
    except (OSError, ValueError):
        return None
    try:
        if start_path.is_file():
            start_path = start_path.parent
    except (OSError, RuntimeError, ValueError):
        return None
    ceiling_path = Path(normalize_path(ceiling)) if ceiling else None
    markers_list = list(markers)
    excludes_list = list(excludes) if excludes else []

    cur = start_path
    for _ in range(_MAX_WALK):
        for exc in excludes_list:                        # exclude vence se casar primeiro
            try:
                if (cur / exc).exists():
                    return None
            except OSError:
                continue
        for marker in markers_list:
            try:
                if (cur / marker).exists():
                    return str(cur)
            except OSError:
                continue
        if ceiling_path is not None and cur == ceiling_path:
            return None
        parent = cur.parent
        if parent == cur:
            return None
        cur = parent
    return None


def workspace_gated(path: str, cwd: str | None = None) -> bool:
    """O LSP deve ativar p/ `path`? True só se está dentro de um worktree git (ou o cwd está)."""
    if find_git_worktree(path):
        return True
    return bool(cwd and find_git_worktree(cwd))


__all__ = ["normalize_path", "find_git_worktree", "is_inside_workspace", "nearest_root", "workspace_gated"]
