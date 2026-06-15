"""Backup/restore do HOME do Okami (#9) — snapshot zipado portátil entre máquinas.

Empacota `~/.okami` (config, memória, sessions, skills, cron) num zip; bancos SQLite são tirados via
`sqlite3.backup()` (consistente, não cópia torn de um .db ao vivo). Restore tem guarda anti zip-slip e
re-chmod 0600 nos segredos. Exclui cache/lixo. Casa com a migração de máquina do dono.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

_EXCLUDE_DIRS = {"__pycache__", "node_modules", ".pytest_cache", ".git", "trash", "tool_outputs"}
_EXCLUDE_SUFFIX = (".tmp", ".pyc", "-wal", "-shm", ".lock", ".sock")
_SECRET_NAMES = {".env", "credentials.json", "auth.json", "cred_pool.json"}


def _is_excluded(rel: Path) -> bool:
    return any(part in _EXCLUDE_DIRS for part in rel.parts) or rel.name.endswith(_EXCLUDE_SUFFIX)


def _snapshot_db(p: Path) -> str | None:
    """Cópia consistente de um SQLite via API (não cópia de bytes ao vivo). None se não for SQLite."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        dst = sqlite3.connect(tmp)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        return tmp
    except sqlite3.Error:
        Path(tmp).unlink(missing_ok=True)
        return None


def create_backup(home, dest_dir, *, stamp: str | None = None) -> Path:
    """Zipa o HOME em dest_dir/okami-backup-<stamp>.zip e devolve o caminho."""
    home = Path(home)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    out = dest / f"okami-backup-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(home.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(home)
            if _is_excluded(rel):
                continue
            if p.suffix == ".db":                     # SQLite → snapshot consistente
                snap = _snapshot_db(p)
                if snap:
                    z.write(snap, str(rel))
                    Path(snap).unlink(missing_ok=True)
                    continue
            z.write(p, str(rel))
    return out


def restore_backup(zip_path, home, *, overwrite: bool = True) -> int:
    """Extrai o backup no HOME (anti zip-slip + re-chmod 0600 nos segredos). Devolve nº de arquivos."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    root = home.resolve()
    n = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            target = (home / info.filename).resolve()
            if root != target and root not in target.parents:   # zip-slip: fora do home → ignora
                continue
            if target.exists() and not overwrite:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as fh:
                fh.write(src.read())
            if target.name in _SECRET_NAMES or target.suffix in (".env", ".pem", ".key"):
                try:
                    os.chmod(target, 0o600)            # segredo restaurado fica privado
                except OSError:
                    pass
            n += 1
    return n
