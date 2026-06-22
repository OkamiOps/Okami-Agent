"""Escrita durável de config/estado (P1.2 — OpenClaw config io / replace-file / backup-rotation).

`secure_write`: escrita ATÔMICA (tmp + fsync + os.replace, sem arquivo meio-escrito) + BACKUP
rotacionado (.bak1..N) + snapshot `.last-good` + chmod. `read_yaml_resilient`: lê YAML e, se o
principal estiver CORROMPIDO, recupera do `.last-good` e depois dos `.bakN` (não perde a config).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def _sib(p: Path, ext: str) -> Path:
    """Irmão do arquivo com sufixo extra (preserva a extensão original: okami.yaml → okami.yaml.bak1)."""
    return Path(str(p) + ext)


def write_atomic(path, data: str, *, mode: int = 0o644) -> Path:
    """Escrita ATÔMICA enxuta (tmp 0600 → escreve → chmod → os.replace), SEM rotação de backup — pra
    estado escrito com frequência (meta de processo, contadores, registries, token OAuth). Nunca deixa
    arquivo meio-escrito/corrompido se o processo cair no meio. mode=0o600 p/ segredo. Cross-plataforma."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix="." + p.name + ".", suffix=".tmp")  # mkstemp já cria 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        from okami.core.platform_compat import secure_chmod
        secure_chmod(tmp, mode=mode)                   # POSIX chmod+verifica / Windows ACL (segredo)
        os.replace(tmp, p)                             # atômico
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return p


def secure_write(path, data: str, *, backups: int = 3, mode: int = 0o644, fsync: bool = True) -> Path:
    """Grava `data` atomicamente, rotaciona backups do conteúdo atual e marca `.last-good`."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():                                    # rotaciona o conteúdo ATUAL antes de sobrescrever
        for i in range(backups, 1, -1):
            src = _sib(p, f".bak{i - 1}")
            if src.exists():
                shutil.copy2(src, _sib(p, f".bak{i}"))
        shutil.copy2(p, _sib(p, ".bak1"))
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix="." + p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            if fsync:
                f.flush()
                os.fsync(f.fileno())                  # garante no disco antes do replace (durabilidade)
        os.replace(tmp, p)                            # atômico
        from okami.core.platform_compat import secure_chmod
        secure_chmod(p, mode=mode)                    # POSIX chmod+verifica / Windows ACL (mkstemp já cria 0600)
        try:
            shutil.copy2(p, _sib(p, ".last-good"))    # snapshot íntegro p/ recovery
        except OSError:
            pass
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return p


def secure_write_yaml(path, obj, **kw) -> Path:
    import yaml
    return secure_write(path, yaml.safe_dump(obj, allow_unicode=True, sort_keys=False), **kw)


def read_yaml_resilient(path, *, default=None):
    """Lê YAML; se corrompido, tenta `.last-good` e depois `.bakN` (recovery). `default` se nada presta."""
    import yaml
    p = Path(path)
    fallback = {} if default is None else default
    candidates = [p, _sib(p, ".last-good")] + [_sib(p, f".bak{i}") for i in range(1, 6)]
    for c in candidates:
        if not c.exists():
            continue
        try:
            obj = yaml.safe_load(c.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            from okami.log import warn
            warn(f"config corrompida em {c.name} — tentando backup")
            continue
        if obj is None:
            if c == p:                                # principal vazio = vazio válido
                return fallback
            continue
        return obj
    return fallback
