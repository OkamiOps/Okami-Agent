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

logger = logging.getLogger("okami")

if not logger.handlers:
    _fmt = logging.Formatter("%(asctime)s okami %(levelname)s %(message)s", "%H:%M:%S")
    _h: logging.Handler = logging.StreamHandler()
    _h.setFormatter(_fmt)
    logger.addHandler(_h)
    _file = os.getenv("OKAMI_LOG_FILE")
    if _file:
        try:
            _fh = logging.FileHandler(_file, encoding="utf-8")
            _fh.setFormatter(_fmt)
            logger.addHandler(_fh)
        except OSError:
            pass
    logger.setLevel(os.getenv("OKAMI_LOG", "WARNING").upper())
    logger.propagate = False


def dbg(msg: str, *, exc_info: bool = False) -> None:
    """Best-effort silencioso (só aparece com OKAMI_LOG=DEBUG)."""
    logger.debug(msg, exc_info=exc_info)


def warn(msg: str, *, exc_info: bool = True) -> None:
    """Falha que afeta comportamento — registra com traceback (não vai pro chat)."""
    logger.warning(msg, exc_info=exc_info)
