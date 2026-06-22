"""Cliente LSP PERSISTENTE (#18 — fecha o gap do #17 vs Hermes agent/lsp/client.py).

Diferente do one-shot (`okami/core/lsp/pyright_client`), este mantém o language server VIVO e o reusa entre
edições: `initialize` uma vez, depois `didOpen` no 1º arquivo e `didChange` nos seguintes — sem pagar o
cold-start (~8s do pyright) a cada write. Uma thread leitora despacha os `publishDiagnostics` por URI; o
`diagnose` registra um Event, manda a mudança e espera o publish daquele arquivo.

Tolerante: binário ausente / servidor que cai / timeout → []. Nunca levanta para fora.
"""
from __future__ import annotations

import subprocess  # noqa: S404 — langserver local confiável, args fixos, sem shell
import threading
from pathlib import Path

from okami.core.lsp.pyright_client import _frame, _read_frames  # reusa framing testado

_INIT_TIMEOUT = 12.0
_DIAG_TIMEOUT = 8.0
_FAR = 10 ** 12          # "deadline" praticamente infinito p/ a thread leitora (sai no EOF)


class PersistentLspClient:
    """Mantém um language server vivo e devolve diagnostics por arquivo, reusando o processo."""

    def __init__(self, proc, root_uri: str):
        self.proc = proc
        self.root_uri = root_uri
        self._diags: dict[str, list] = {}
        self._events: dict[str, threading.Event] = {}
        self._versions: dict[str, int] = {}
        self._opened: set[str] = set()
        self._init_done = threading.Event()
        self._lock = threading.Lock()
        self._alive = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    @classmethod
    def spawn(cls, binary: str, args, root: str) -> "PersistentLspClient | None":
        """Sobe o servidor e devolve o cliente (ou None se falhar)."""
        try:
            proc = subprocess.Popen(  # noqa: S603 — binary do catálogo/PATH, args fixos, sem shell
                [binary, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL)
        except (OSError, ValueError):
            return None
        return cls(proc, Path(root).resolve().as_uri())

    def _read_loop(self) -> None:
        for msg in _read_frames(self.proc.stdout, _FAR):
            method = msg.get("method")
            if msg.get("id") == 1 and "result" in msg:           # resposta do initialize
                self._init_done.set()
            if method == "textDocument/publishDiagnostics":
                params = msg.get("params") or {}
                uri = params.get("uri")
                if uri:
                    self._diags[uri] = params.get("diagnostics") or []
                    ev = self._events.get(uri)
                    if ev:
                        ev.set()
        self._alive = False

    def _send(self, payload: dict) -> None:
        try:
            self.proc.stdin.write(_frame(payload))
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError, AttributeError):
            self._alive = False

    def _ensure_init(self) -> None:
        if self._init_done.is_set():
            return
        self._send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "processId": None, "rootUri": self.root_uri,
            "capabilities": {"textDocument": {"publishDiagnostics": {}}},
            "initializationOptions": {}}})
        self._init_done.wait(_INIT_TIMEOUT)
        self._send({"jsonrpc": "2.0", "method": "initialized", "params": {}})

    def diagnose(self, uri: str, text: str, *, language_id: str = "python",
                 timeout: float = _DIAG_TIMEOUT) -> list:
        """Diagnostics do `text` (salvo como `uri`). 1ª vez = didOpen; depois = didChange (reusa o server)."""
        if not self._alive:
            return []
        with self._lock:
            self._ensure_init()
            ev = threading.Event()
            self._events[uri] = ev
            if uri in self._opened:
                self._versions[uri] = self._versions.get(uri, 1) + 1
                self._send({"jsonrpc": "2.0", "method": "textDocument/didChange", "params": {
                    "textDocument": {"uri": uri, "version": self._versions[uri]},
                    "contentChanges": [{"text": text}]}})
            else:
                self._opened.add(uri)
                self._versions[uri] = 1
                self._send({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
                    "textDocument": {"uri": uri, "languageId": language_id, "version": 1, "text": text}}})
        got = ev.wait(timeout)
        if not got:
            return []
        with self._lock:                              # lê _diags SOB lock: o _read_loop escreve nele sem
            return self._diags.get(uri, [])           # lock; sem isto é data-race (read-after-release)

    def close(self) -> None:
        """Encerra o servidor educadamente; mata se travar."""
        self._alive = False
        try:
            self._send({"jsonrpc": "2.0", "id": 99, "method": "shutdown", "params": None})
            self._send({"jsonrpc": "2.0", "method": "exit", "params": None})
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=1.0)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def pid(self) -> int | None:
        return getattr(self.proc, "pid", None)


__all__ = ["PersistentLspClient"]
