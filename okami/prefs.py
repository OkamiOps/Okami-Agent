"""Preferências de UI persistentes (prefs.json em $OKAMI_HOME) — fonte ÚNICA, merge-safe.

Tema (/skin), verbosidade dos tool-calls (/details) e afins moram aqui. NUNCA levanta (é cosmético):
IO/JSON corrompido → cai no default. Escrita ATÔMICA (tmp+rename) e MERGE (preserva as outras chaves) →
REPL e TUI gravam no mesmo arquivo sem se sobrescrever (base do "AppPrefs unificado").
"""
from __future__ import annotations

import json
import os
import tempfile


def _path():
    from okami.home import okami_home
    return okami_home() / "prefs.json"


def load_prefs() -> dict:
    """Todo o prefs.json como dict. {} se ausente/corrompido (nunca levanta)."""
    try:
        p = _path()
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def get_pref(key: str, default=None):
    """Valor de `key`, ou `default` se ausente/None."""
    v = load_prefs().get(key)
    return v if v is not None else default


def set_pref(key: str, value) -> bool:
    """Grava key=value PRESERVANDO as outras chaves (merge). Atômico. False se falhou (nunca levanta)."""
    try:
        from okami.home import okami_home
        home = okami_home()
        home.mkdir(parents=True, exist_ok=True)
        data = load_prefs()
        data[key] = value
        fd, tmp = tempfile.mkstemp(prefix="prefs.", suffix=".tmp", dir=str(home))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, _path())
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:  # noqa: BLE001
                pass
            raise
        return True
    except Exception:  # noqa: BLE001
        return False
