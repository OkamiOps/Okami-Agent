"""Ponto de entrada de MÓDULO do CLI: `python -m okami.cli ...`.

O gateway em background (okami/cli/commands/gateway.py) e o serviço (okami/gateway/service.py) relançam
o processo via `sys.executable -m okami.cli ...` — assim não dependem do launcher `okami` estar no PATH
(que pode não estar num spawn destacado/serviço). `okami.cli` é um PACOTE, então sem este `__main__.py`
o relance falhava na hora ("No module named okami.cli.__main__"), e o gateway "subia" mas parava logo.
"""
from __future__ import annotations

from okami.cli import app

if __name__ == "__main__":
    app()
