"""#9: o log do agente (OKAMI_LOG_FILE) ROTACIONA por tamanho — num gateway 24/7 não cresce sem teto."""
from __future__ import annotations

import logging


def test_file_handler_is_rotating():
    from logging.handlers import RotatingFileHandler

    from okami.log import _file_handler
    h = _file_handler("/tmp/okami-test.log", logging.Formatter("%(message)s"))
    assert isinstance(h, RotatingFileHandler)
    assert h.maxBytes > 0 and h.backupCount >= 1     # tem teto + mantém alguns backups
