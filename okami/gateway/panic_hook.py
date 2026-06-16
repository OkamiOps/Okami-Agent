"""Panic-hook → log de crash do gateway/TUI (#11, port do Hermes tui_gateway/server.py).

Crash não-tratado numa sessão TUI/gateway some sem forense: stdout é pipe JSON-RPC, stderr se perde
antes da TUI ler. Instala sys.excepthook + threading.excepthook p/ logar o traceback completo num
arquivo E emitir 1-linha no stderr (que a Activity/feed consegue mostrar). Encadeia no hook original.
"""
from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path


def format_crash(exc_type, exc, tb) -> str:
    """1-linha p/ stderr: 'Tipo: primeira linha da mensagem'."""
    msg = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    name = getattr(exc_type, "__name__", str(exc_type))
    return f"[okami-gateway-crash] {name}: {msg}" if msg else f"[okami-gateway-crash] {name}"


def write_crash(log_path, exc_type, exc, tb) -> None:
    """Append do traceback completo + timestamp-agnóstico no arquivo de crash. Best-effort."""
    try:
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(traceback.format_exception(exc_type, exc, tb))
        with p.open("a", encoding="utf-8") as f:
            f.write("\n===== crash =====\n" + body)
    except Exception:  # noqa: BLE001 — logar crash NUNCA pode crashar
        pass


def install_panic_hook(log_path) -> None:
    """Instala excepthook (main + threads) que loga o crash e emite 1-linha no stderr, encadeando no
    hook original. Idempotente o suficiente p/ chamar no boot do gateway/TUI."""
    prev = sys.excepthook

    def _hook(exc_type, exc, tb):
        write_crash(log_path, exc_type, exc, tb)
        try:
            print(format_crash(exc_type, exc, tb), file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass
        try:
            prev(exc_type, exc, tb)
        except Exception:  # noqa: BLE001
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook

    def _thread_hook(args):
        write_crash(log_path, args.exc_type, args.exc_value, args.exc_traceback)
        try:
            print(format_crash(args.exc_type, args.exc_value, args.exc_traceback), file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass

    threading.excepthook = _thread_hook


__all__ = ["format_crash", "write_crash", "install_panic_hook"]
