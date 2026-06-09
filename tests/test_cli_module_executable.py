"""Regressão: o CLI TEM que ser executável via `python -m okami.cli`.

O gateway (background) e o serviço relançam o processo assim — `sys.executable -m okami.cli ...` —
pra não depender do launcher `okami` estar no PATH. Sem `okami/cli/__main__.py`, esse relance morria
na hora com "No module named okami.cli.__main__; 'okami.cli' is a package and cannot be directly
executed": o pai dizia "gateway no ar em background (pid X)" mas o filho parava logo em seguida.
"""
from __future__ import annotations

import subprocess
import sys


def test_okami_cli_runnable_as_module():
    r = subprocess.run([sys.executable, "-m", "okami.cli", "--help"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"`python -m okami.cli` falhou (gateway background quebraria): {r.stderr[-500:]}"
    assert "okami" in (r.stdout + r.stderr).lower()
