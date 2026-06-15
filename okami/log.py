"""Logger central do Okami (#4 do self-review) — best-effort que NÃO fica mudo.

Antes havia muito `except Exception: pass` escondendo falha real (learning, provider, memória, skill
scan). Aqui:
- `dbg(...)`  → falha best-effort de verdade (TTS, compaction, hook opcional): silenciosa por padrão.
- `warn(...)` → falha que AFETA comportamento: vai pro stderr/arquivo com traceback, sem poluir a UX
  (vai pro logger, não pro chat).

Nível por env `OKAMI_LOG` (default WARNING). Arquivo opcional por `OKAMI_LOG_FILE`.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

logger = logging.getLogger("okami")

_LOG_MAX_BYTES = 5 * 1024 * 1024   # #9: teto por arquivo (gateway 24/7 não enche o disco)
_LOG_BACKUPS = 3                   # mantém okami.log.1..3


def _file_handler(path: str, fmt: logging.Formatter) -> RotatingFileHandler:
    """Handler de arquivo que ROTACIONA por tamanho (em vez de crescer sem teto)."""
    h = RotatingFileHandler(path, maxBytes=_LOG_MAX_BYTES, backupCount=_LOG_BACKUPS, encoding="utf-8")
    h.setFormatter(fmt)
    return h


if not logger.handlers:
    _fmt = logging.Formatter("%(asctime)s okami %(levelname)s %(message)s", "%H:%M:%S")
    _h: logging.Handler = logging.StreamHandler()
    _h.setFormatter(_fmt)
    logger.addHandler(_h)
    _file = os.getenv("OKAMI_LOG_FILE")
    if _file:
        try:
            logger.addHandler(_file_handler(_file, _fmt))   # #9: rotação por tamanho
        except OSError:
            pass
    logger.setLevel(os.getenv("OKAMI_LOG", "WARNING").upper())
    logger.propagate = False


def _safe(msg: str) -> str:
    """Mascara segredos ANTES de ir pro log (redator central)."""
    try:
        from okami.core.redact import redact
        return redact(msg)
    except Exception:  # noqa: BLE001 — log nunca derruba nada
        return msg


def dbg(msg: str, *, exc_info: bool = False) -> None:
    """Best-effort silencioso (só aparece com OKAMI_LOG=DEBUG)."""
    logger.debug(_safe(msg), exc_info=exc_info)


def warn(msg: str, *, exc_info: bool = True) -> None:
    """Falha que afeta comportamento — registra com traceback (não vai pro chat)."""
    logger.warning(_safe(msg), exc_info=exc_info)
