"""Hub de skills — gestão local das skills instaladas com PROVENIÊNCIA (lockfile). Liga o verify()
que estava dormente: list (o que está instalado, de onde, íntegro?), remove (desinstala + tira do
lock). Instalar é `okami learn <fonte>` (quarentena + scan); atualizar re-busca da fonte registrada.

Honesto: NÃO há servidor de catálogo remoto — o 'hub' aqui é a curadoria do que você já tem, com
trilha de origem e detecção de adulteração. Um catálogo central pode vir depois sobre esta base."""

from __future__ import annotations

import shutil
from pathlib import Path

from okami.skills.lockfile import LOCK_NAME, load_lock, verify


def installed(lock_root, skills_root) -> list[dict]:
    """Lista as skills registradas no lockfile, com origem/versão + se estão PRESENTES e ÍNTEGRAS."""
    lock = load_lock(lock_root)
    out: list[dict] = []
    for name, e in sorted(lock.get("skills", {}).items()):
        sd = Path(skills_root) / name
        present = (sd / "SKILL.md").exists() or sd.exists()
        out.append({"name": name, "source": e.get("source", ""), "version": e.get("version", ""),
                    "installed_at": e.get("installed_at", 0), "present": present,
                    "ok": present and verify(lock_root, name, sd)})
    return out


def remove(lock_root, skills_root, name: str) -> bool:
    """Desinstala a skill (apaga a pasta) e tira a entrada do lockfile. False se não havia nada."""
    sd = Path(skills_root) / name
    lock = load_lock(lock_root)
    in_lock = name in lock.get("skills", {})
    existed = sd.exists() or in_lock
    shutil.rmtree(sd, ignore_errors=True)
    if in_lock:
        from okami.core.safe_io import secure_write
        import json
        del lock["skills"][name]
        secure_write(Path(lock_root) / LOCK_NAME,
                     json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return existed
