"""Smoke test de BOOT do `okami chat` — roda o comando DE VERDADE (subprocess) e sai na hora.

Motivação: as closures do REPL (_on_event/_toolbar) vivem dentro de chat()/_run_repl e não são
importáveis isoladamente, então unit tests não pegam um crash de inicialização (ex.: usar `ep` antes
de `ep = AgentEndpoint(...)` → UnboundLocalError). A única forma de blindar é EXECUTAR o comando.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_okami_chat_boots_without_traceback(tmp_path):
    # roda `okami chat` com /exit imediato; não deve estourar traceback na inicialização.
    env = dict(os.environ, OKAMI_HOME=str(tmp_path), NO_COLOR="1")
    proc = subprocess.run(
        [sys.executable, "-m", "okami.cli", "chat"],
        input="/exit\n", capture_output=True, text=True, timeout=90,
        cwd=str(REPO), env=env,
    )
    out = proc.stdout + proc.stderr
    # o bug de regressão específico + qualquer erro de escopo de boot
    assert "UnboundLocalError" not in out, out[-1500:]
    assert "Traceback (most recent call last)" not in out, out[-2000:]
