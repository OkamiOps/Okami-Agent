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


def test_okami_chat_honors_provider_flag(tmp_path):
    # `okami chat -p <provider>` deve MOSTRAR o provider da flag no banner, não o default do yaml.
    # Regressão: o -p era resolvido mas o REPL/banner usavam cfg.default_provider → flag ignorada.
    import re
    yaml = (REPO / "okami.yaml").read_text(encoding="utf-8")
    if "minimax" not in yaml or "mimo" not in yaml:
        import pytest
        pytest.skip("okami.yaml de referência não tem minimax+mimo p/ o teste de override")
    # default = mimo; vamos pedir -p minimax e exigir que o banner mostre MiniMax
    yaml_mimo = re.sub(r"(?m)^default_provider:.*$", "default_provider: mimo", yaml)
    (tmp_path / "okami.yaml").write_text(yaml_mimo, encoding="utf-8")
    env = dict(os.environ, OKAMI_HOME=str(tmp_path), NO_COLOR="1")
    proc = subprocess.run(
        [sys.executable, "-m", "okami.cli", "chat", "-p", "minimax"],
        input="/exit\n", capture_output=True, text=True, timeout=90,
        cwd=str(tmp_path), env=env,
    )
    out = proc.stdout + proc.stderr
    assert "Traceback (most recent call last)" not in out, out[-2000:]
    assert "MiniMax" in out or "minimax" in out, f"banner nao mostrou o provider da flag (-p minimax):\n{out[-1200:]}"
