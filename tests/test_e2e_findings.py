"""Bugs achados RODANDO o app de ponta a ponta (não revisando código).

#1 process_signal: lstrip('SIG') comia QUALQUER S/I/G inicial → 'INT'→'NT', 'STOP'→'TOP', 'SIGINT'→'NT'
   → sinal inválido → signal() retornava False SEM sinalizar (falha muda). A tool anuncia 'INT p/ Ctrl-C'
   e 'STOP' — ambos quebrados. Fix: removeprefix('SIG') nos 3 sites (processes.signal x2 + endpoint)."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path


def test_process_signal_int_stop_actually_signal():
    from okami.core.processes import ProcessManager
    pm = ProcessManager(Path(tempfile.mkdtemp()))

    def _pid(p):
        return p["id"] if isinstance(p, dict) else p

    # INT mata o sleep (era False+no-op por causa do lstrip)
    p = pm.start("sleep 30")
    pid = _pid(p)
    time.sleep(0.2)
    assert pm.signal(pid, "INT") is True                 # antes: False (parse virava 'NT')
    time.sleep(0.3)
    st = pm.poll(pid)
    assert (st or {}).get("status") == "exited"          # INT realmente encerrou
    pm.kill(pid)

    # STOP pausa (não mata) — também era quebrado ('TOP')
    p2 = pm.start("sleep 30")
    pid2 = _pid(p2)
    time.sleep(0.2)
    assert pm.signal(pid2, "STOP") is True
    assert pm.signal(pid2, "SIGINT") is True             # forma com prefixo SIG também (era 'NT')
    pm.kill(pid2)


def test_signal_name_normalization():
    """Garante o parse correto (removeprefix, não lstrip)."""
    for raw, want in [("INT", "INT"), ("STOP", "STOP"), ("SIGINT", "INT"),
                      ("SIGSTOP", "STOP"), ("TERM", "TERM"), ("SIGTERM", "TERM")]:
        assert raw.upper().removeprefix("SIG") == want
        # o bug antigo: lstrip comia letras de mais
        if raw in ("INT", "STOP", "SIGINT", "SIGSTOP"):
            assert raw.upper().lstrip("SIG") != want      # prova que lstrip estava ERRADO
