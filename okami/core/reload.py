"""Hot-reload de config (#12 — safe reload sem reiniciar).

Recarrega okami.yaml/okami.local.yaml em quente, mas SÓ aplica se a nova config VALIDAR (constrói a
OkamiConfig sem erro). Config quebrada → mantém a antiga e devolve o erro (nunca derruba o gateway).
Só campos SEGUROS são re-aplicados em quente (aprovação, sandbox, persona, modelo via cfg) — trocar
de canal/agent_id exige re-wiring → não é hot-reloadable (continua precisando de restart).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class ReloadResult:
    changed: bool = False
    ok: bool = False
    error: str = ""
    config: object | None = None


class ConfigReloader:
    """Vigia mtime dos arquivos de config; em mudança, recarrega+valida (best-effort)."""

    def __init__(self, paths, *, loader: Callable[[], object] | None = None, clock=time.time):
        self.paths = [Path(p) for p in paths]
        self._clock = clock
        if loader is None:
            from okami.config import load_config
            loader = load_config
        self.loader = loader
        self._mtimes = self._snapshot()

    def _snapshot(self) -> dict:
        out = {}
        for p in self.paths:
            try:
                out[str(p)] = p.stat().st_mtime
            except OSError:
                out[str(p)] = 0.0
        return out

    def changed(self) -> bool:
        return self._snapshot() != self._mtimes

    def poll(self) -> ReloadResult:
        """Sem mudança → changed=False. Com mudança → recarrega; ok=False+error se a config quebrou."""
        if not self.changed():
            return ReloadResult(changed=False)
        self._mtimes = self._snapshot()                  # marca como visto (não fica reclamando todo poll)
        try:
            cfg = self.loader()
        except Exception as e:  # noqa: BLE001 — config inválida não derruba; mantém a anterior
            return ReloadResult(changed=True, ok=False, error=str(e))
        return ReloadResult(changed=True, ok=True, config=cfg)
