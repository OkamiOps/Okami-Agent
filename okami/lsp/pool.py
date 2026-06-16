"""Pool de clientes LSP persistentes por sessão (#18). Reusa um server VIVO por (servidor, raiz) entre
edições, em vez de cold-start a cada write. Roteia por extensão via o catálogo `servers`."""
from __future__ import annotations

import threading
from pathlib import Path

from okami.lsp.client import PersistentLspClient
from okami.lsp.servers import binary_available, server_for_path
from okami.lsp.workspace import find_git_worktree


class LspPool:
    """Mantém clientes LSP vivos por (binário, raiz). `diagnose_path` resolve o servidor pela extensão."""

    def __init__(self):
        self._clients: dict[tuple[str, str], PersistentLspClient | None] = {}
        self._lock = threading.Lock()

    def _client_for(self, server, root: str) -> PersistentLspClient | None:
        key = (server.binary, root)
        with self._lock:
            client = self._clients.get(key, "missing")
            if client == "missing":
                client = PersistentLspClient.spawn(server.binary, server.args, root)
                self._clients[key] = client            # None se o spawn falhou (não retenta)
            return client if client != "missing" else None

    def diagnose_path(self, workspace, rel: str, text: str) -> list:
        """Diagnostics do `text` salvo como `rel` em `workspace`. [] se gateado-off / sem servidor.
        GATE: só dentro de repo git (igual ao one-shot)."""
        path = str(Path(workspace) / rel)
        server = server_for_path(path)
        if server is None or not binary_available(server):
            return []
        root = find_git_worktree(path)                 # 1 só walk (era 2)
        if not root:                                   # fora de repo git → off (não sobe daemon)
            return []
        client = self._client_for(server, root)
        if client is None:
            return []
        uri = Path(path).resolve().as_uri()
        lang = (server.languages[0] if server.languages else "plaintext")
        return client.diagnose(uri, text, language_id=lang)

    def shutdown(self) -> None:
        """Encerra todos os servidores (fim de sessão)."""
        with self._lock:
            clients = [c for c in self._clients.values() if c]
            self._clients.clear()
        for c in clients:
            c.close()

    def live_count(self) -> int:
        with self._lock:
            return sum(1 for c in self._clients.values() if c)


__all__ = ["LspPool"]
