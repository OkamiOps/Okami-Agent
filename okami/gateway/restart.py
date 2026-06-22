"""Auto-restart do gateway a partir do chat (/restart) — estilo Hermes (gateway/restart.py).

O gateway em background não tem service manager p/ relançá-lo; quem sabe parar-e-subir é o
próprio CLI (`okami gateway restart`). Então o /restart DELEGA: spawna o CLI destacado
(start_new_session → sobrevive à nossa morte), que manda SIGTERM aqui, espera morrer e sobe
um gateway novo com o código/config atuais.

Guarda: só quando NÓS somos o processo do pidfile (background gerenciado). Foreground/serviço
do SO ficam de fora — spawnar outro gateway ali criaria DOIS processos disputando o polling
do Telegram (conflito de getUpdates).
"""
from __future__ import annotations

import os
import sys

from okami.i18n import t as _tr


def _managed_pid() -> int | None:
    """PID do pidfile do gateway em background (~/.okami/runtime/gateway.pid), ou None."""
    from okami.home import okami_home
    pidfile = okami_home() / "runtime" / "gateway.pid"
    try:
        raw = pidfile.read_text(encoding="utf-8").strip()
        return int(raw) if raw.isdigit() else None
    except OSError:
        return None


def schedule_self_restart() -> tuple[bool, str]:
    """Agenda o restart do PRÓPRIO gateway via CLI destacado. (ok, mensagem p/ o chat)."""
    import subprocess
    if _managed_pid() != os.getpid():
        return False, _tr("gw.restart_unmanaged",
                          _default="gateway não está em background gerenciado — reinicie pelo terminal: "
                                   "okami gateway restart (ou okami service restart).")
    flags = {}
    if os.name == "nt":
        flags["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        flags["start_new_session"] = True                # sobrevive à nossa morte (é ele quem nos mata)
    subprocess.Popen([sys.executable, "-m", "okami.cli", "gateway", "restart"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, cwd=os.getcwd(), **flags)
    return True, _tr("gw.restarting",
                     _default="reiniciando o gateway — volto em segundos com o código/config novos.")
