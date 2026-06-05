"""Lockfile + proveniência de skills (P1.5) — o QUE foi instalado, de ONDE e com qual HASH.

`skills-lock.json` guarda por skill: source, sha256 do conteúdo, versão e quando. Dá pin/auditoria
e DETECÇÃO DE ADULTERAÇÃO (a skill mudou no disco desde que você aprovou?). É commitável (igual a um
package-lock). O scan de segurança continua sendo o gate de INSTALAÇÃO; aqui é a trilha pós-instalação.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

LOCK_NAME = "skills-lock.json"


def skill_hash(skill_dir) -> str:
    """sha256 determinístico do conteúdo (arquivos ordenados; path + bytes). Sensível a qualquer mudança."""
    d = Path(skill_dir)
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(d)).encode("utf-8"))
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def load_lock(root) -> dict:
    p = Path(root) / LOCK_NAME
    if not p.exists():
        return {"skills": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {"skills": {}}
    except ValueError:
        return {"skills": {}}


def record(root, name: str, *, source: str, skill_dir, version: str = "", ts: float | None = None) -> dict:
    """Registra/atualiza a proveniência de uma skill no lockfile (escrita durável via secure_write)."""
    from okami.core.safe_io import secure_write
    lock = load_lock(root)
    lock.setdefault("skills", {})[name] = {
        "source": source,
        "sha256": skill_hash(skill_dir),
        "version": version,
        "installed_at": time.time() if ts is None else ts,
    }
    secure_write(Path(root) / LOCK_NAME,
                 json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return lock


def verify(root, name: str, skill_dir) -> bool:
    """True se a skill no disco bate com o hash registrado (sem adulteração). False se difere/ausente."""
    entry = load_lock(root).get("skills", {}).get(name)
    return bool(entry) and entry.get("sha256") == skill_hash(skill_dir)
