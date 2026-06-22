"""Núcleo compartilhado do plugin disk-cleanup (importado por track.py e clean.py). Auto-contido (só
stdlib) — sem importar okami, p/ rodar sob qualquer python. Classifica EFÊMEROS de forma conservadora e
guarda o estado em OKAMI_HOME/disk-cleanup/tracked.json, com caminhos por realpath p/ casar /var↔/private."""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path

# Conservador DE PROPÓSITO: só o que o agente claramente marcou como descartável. NUNCA classifica por
# "está sob um diretório temp do SO" (a própria workspace do agente pode morar lá — apagaria trabalho real).
_EPHEMERAL_EXT = (".tmp", ".temp", ".bak", ".swp", ".swo", ".scratch", ".orig", ".rej", "~")
_EPHEMERAL_DIR_SEGMENTS = {"tmp", "temp", "scratch", ".scratch", ".okami-scratch"}
_WRITE_TOOLS = {"write_file", "edit_file", "str_replace", "create_file"}


def state_path() -> Path:
    home = os.environ.get("OKAMI_HOME") or str(Path.home() / ".okami")
    d = Path(home) / "disk-cleanup"
    d.mkdir(parents=True, exist_ok=True)
    return d / "tracked.json"


def load_state() -> dict:
    f = state_path()
    try:
        s = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        return s if isinstance(s, dict) else {}
    except (ValueError, OSError):
        return {}


def save_state(state: dict) -> None:
    try:
        state_path().write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def is_ephemeral(abs_path: str, cwd: str) -> bool:
    """Efêmero se: extensão/nome descartável; OU um segmento ABAIXO do cwd é tmp/temp/scratch (escolha
    deliberada do agente); OU casa um glob opt-in (OKAMI_DISKCLEAN_GLOBS). Ancorar no cwd evita que
    diretórios-ancestrais (ex.: /var/folders/.../T) disparem o classificador."""
    p = Path(abs_path)
    name = p.name
    if name.endswith(_EPHEMERAL_EXT) or name.startswith("~"):
        return True
    try:
        rel_parts = {seg.lower() for seg in p.relative_to(cwd).parts[:-1]}   # só os dirs ABAIXO do cwd
    except ValueError:
        rel_parts = set()
    if rel_parts & _EPHEMERAL_DIR_SEGMENTS:
        return True
    for glob in (os.environ.get("OKAMI_DISKCLEAN_GLOBS") or "").split(","):
        glob = glob.strip()
        if glob and fnmatch.fnmatch(name, glob):
            return True
    return False


def candidate_paths(tool: str, args: dict, cwd: str) -> list[str]:
    """Caminhos absolutos (realpath) que ESTA tool vai criar/escrever."""
    rels: list[str] = []
    if tool in _WRITE_TOOLS:
        path = args.get("path") or args.get("file")
        if isinstance(path, str) and path:
            rels.append(path)
    elif tool == "apply_patch":
        patch = args.get("patch")
        if not isinstance(patch, str):                       # payload malformado (lista/None) → ignora
            return []
        for line in patch.splitlines():
            line = line.strip()
            for marker in ("*** Add File:", "*** Update File:"):
                if line.startswith(marker):
                    rels.append(line[len(marker):].strip())
    out = []
    for rel in rels:
        ab = rel if os.path.isabs(rel) else os.path.join(cwd, rel)
        out.append(os.path.realpath(ab))
    return out


def project_key(cwd: str) -> str:
    return os.path.realpath(cwd)


def load_payload() -> dict:
    import sys
    raw = os.environ.get("OKAMI_HOOK_PAYLOAD")
    if raw is None and not sys.stdin.isatty():
        raw = sys.stdin.read()
    try:
        obj = json.loads(raw or "{}")
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}
