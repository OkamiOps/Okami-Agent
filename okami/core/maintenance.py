"""Manutenção / gestão de disco (P2) — limpa lock órfão, conserta permissões e poda temporários.

Funções puras-testáveis que `okami clean` e `doctor --fix` usam. Conservador de propósito: NÃO apaga
transcript/checkpoint ativos; mexe em lock órfão, perms do .env e temporários (áudio/.tmp).
"""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

_SKIP = {".git", "node_modules", ".venv", "__pycache__"}


def clean_stale_locks(root, *, stale: float = 300.0) -> list[str]:
    """Remove arquivos `.lock` órfãos (mtime > `stale`s) sob `root`. Devolve os caminhos removidos."""
    removed = []
    now = time.time()
    for lk in Path(root).rglob("*.lock"):
        if any(part in _SKIP for part in lk.parts):
            continue
        try:
            if now - lk.stat().st_mtime > stale:
                lk.unlink()
                removed.append(str(lk))
        except OSError:
            pass
    return removed


def fix_env_perms(env_path) -> bool:
    """Garante 0600 no .env de segredos. True se PRECISOU corrigir."""
    p = Path(env_path)
    if not p.exists():
        return False
    try:
        if stat.S_IMODE(p.stat().st_mode) != 0o600:
            os.chmod(p, 0o600)
            return True
    except OSError:
        pass
    return False


def prune_temp(root, *, patterns=("*.tmp", ".env.*.tmp")) -> tuple[list[str], int]:
    """Remove temporários deixados pra trás (tmp de escrita atômica). Devolve (removidos, bytes)."""
    removed, freed = [], 0
    for pat in patterns:
        for f in Path(root).rglob(pat):
            if not f.is_file() or any(part in _SKIP for part in f.parts):
                continue
            try:
                sz = f.stat().st_size
                f.unlink()
                removed.append(str(f))
                freed += sz
            except OSError:
                pass
    return removed, freed


def prune_audio(root) -> tuple[list[str], int]:
    """Limpa áudio temporário (voz/TTS): .okami/voice/* e okami_say*.mp3. Devolve (removidos, bytes)."""
    removed, freed = [], 0
    targets = list((Path(root) / ".okami" / "voice").glob("*")) + list(Path(root).glob("okami_say*.mp3"))
    for f in targets:
        try:
            if f.is_file():
                sz = f.stat().st_size
                f.unlink()
                removed.append(str(f))
                freed += sz
        except OSError:
            pass
    return removed, freed


def clean_workspace(root, *, lock_stale: float = 300.0) -> dict:
    """Faxina padrão (conservadora) — devolve um relatório com contagens e bytes liberados."""
    locks = clean_stale_locks(root, stale=lock_stale)
    rm_t, freed_t = prune_temp(root)
    rm_a, freed_a = prune_audio(root)
    return {
        "locks_removed": len(locks),
        "temp_removed": len(rm_t),
        "audio_removed": len(rm_a),
        "bytes_freed": freed_t + freed_a,
    }
