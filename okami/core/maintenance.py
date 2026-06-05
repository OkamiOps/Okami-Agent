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


def prune_by_age_and_count(directory, *, pattern: str = "*", days: float = 30.0,
                           keep: int = 20, exclude=()) -> tuple[list[str], int]:
    """Poda arquivos: MANTÉM os `keep` mais recentes; remove o resto que for mais velho que `days`.
    Devolve (removidos, bytes). `exclude` protege nomes (ex.: journal.jsonl)."""
    d = Path(directory)
    if not d.exists():
        return [], 0
    files = sorted((f for f in d.glob(pattern) if f.is_file() and f.name not in set(exclude)),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    cutoff = time.time() - days * 86400
    removed, freed = [], 0
    for f in files[keep:]:                          # além dos `keep` mais novos
        try:
            if f.stat().st_mtime < cutoff:
                sz = f.stat().st_size
                f.unlink()
                removed.append(str(f))
                freed += sz
        except OSError:
            pass
    return removed, freed


def prune_sessions(root, *, days: float = 30.0, keep: int = 10) -> tuple[list[str], int]:
    """Poda transcripts ARQUIVADOS (`*.reset.jsonl`) de sessions/groups — quota por idade+contagem."""
    removed, freed = [], 0
    for sub in ("sessions", "groups"):
        r, fr = prune_by_age_and_count(Path(root) / ".okami" / sub,
                                       pattern="*.reset.jsonl", days=days, keep=keep)
        removed += r
        freed += fr
    return removed, freed


def prune_checkpoints(root, *, days: float = 14.0, keep: int = 50) -> tuple[list[str], int]:
    """Poda snapshots antigos de checkpoints — MANTÉM o journal.jsonl (rollback) sempre."""
    return prune_by_age_and_count(Path(root) / ".okami" / "checkpoints",
                                  days=days, keep=keep, exclude={"journal.jsonl"})


def prune_processes(root, *, ttl_hours: float = 24.0) -> list[str]:
    """Remove processos em background JÁ TERMINADOS há mais de `ttl_hours` (cleanup TTL #1/#8)."""
    from okami.core.processes import ProcessManager
    try:
        return ProcessManager(root).prune(ttl_seconds=ttl_hours * 3600.0)
    except Exception:  # noqa: BLE001
        return []


def clean_workspace(root, *, lock_stale: float = 300.0, proc_ttl_hours: float = 24.0) -> dict:
    """Faxina padrão (conservadora) — devolve um relatório com contagens e bytes liberados."""
    locks = clean_stale_locks(root, stale=lock_stale)
    rm_t, freed_t = prune_temp(root)
    rm_a, freed_a = prune_audio(root)
    rm_p = prune_processes(root, ttl_hours=proc_ttl_hours)
    return {
        "locks_removed": len(locks),
        "temp_removed": len(rm_t),
        "audio_removed": len(rm_a),
        "processes_removed": len(rm_p),
        "bytes_freed": freed_t + freed_a,
    }
