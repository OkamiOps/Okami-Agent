"""Browser supervisor — listener CDP persistente (#12, port do Hermes tools/browser_supervisor.py).

Mantém um snapshot thread-safe do estado do browser a partir de eventos CDP (`Page`/`Runtime`/`Target`):
diálogos pendentes (alert/confirm/prompt) e árvore de frames (OOPIF/worker). Sem isto, um modal trava a
thread do agente e iframe/worker viram falha cega. Aqui mora a LÓGICA de evento→snapshot + a política de
diálogo (testável); a conexão WebSocket CDP é um wrapper fino por cima.
"""
from __future__ import annotations

import threading


class BrowserSupervisor:
    """Acumula estado a partir de eventos CDP. Thread-safe (lock interno)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._dialogs: list[dict] = []
        self._frames: dict[str, str | None] = {}     # frameId → parentFrameId

    def handle_event(self, method: str, params: dict) -> None:
        params = params or {}
        with self._lock:
            if method == "Page.javascriptDialogOpening":
                self._dialogs.append({"type": params.get("type", "alert"),
                                      "message": params.get("message", "")})
            elif method == "Page.javascriptDialogClosed":
                if self._dialogs:
                    self._dialogs.pop(0)
            elif method == "Page.frameAttached":
                fid = params.get("frameId")
                if fid:
                    self._frames[fid] = params.get("parentFrameId")
            elif method == "Page.frameDetached":
                self._frames.pop(params.get("frameId"), None)

    def snapshot(self) -> dict:
        with self._lock:
            return {"pending_dialogs": list(self._dialogs), "frames": dict(self._frames)}


def dialog_decision(dialog: dict, policy: str) -> dict:
    """Decide o que fazer com um diálogo dado a política:
    - 'auto_accept': aceita (OK).
    - 'auto_dismiss': dispensa (Cancel).
    - 'must_respond' (default): defere — espera o agente decidir."""
    pol = (policy or "must_respond").lower()
    if pol == "auto_accept":
        return {"accept": True, "defer": False}
    if pol == "auto_dismiss":
        return {"accept": False, "defer": False}
    return {"accept": False, "defer": True}


__all__ = ["BrowserSupervisor", "dialog_decision"]
