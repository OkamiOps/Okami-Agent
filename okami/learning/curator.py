"""Curator (estilo Hermes curator.py) — tier LENTO de consolidação das skills AUTO-criadas.

Não conserta lixo (a fonte já está estancada pelo gate determinístico + review model-driven); arruma o
que ACUMULA: arquiva skills auto-criadas sem uso há muito tempo (LRU) e funde as estreitas/duplicadas em
"umbrellas" de classe (passada model-driven). Invariantes copiados do Hermes:
  • NUNCA deleta — move p/ .archive/ e tira SNAPSHOT (tar.gz) antes; `okami curator rollback` desfaz.
  • só toca skill AUTO-criada (origin: agent | auto-distilled); curada/instalada e PINADA são intocáveis.
  • --dry-run reporta sem mutar.
"""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import time
from pathlib import Path

USAGE_FILE = ".usage.json"
ARCHIVE_DIR = ".archive"
SNAP_DIR = ".snapshots"
_DAY = 86400.0


# ---------------------------------------------------------------- uso (LRU telemetry, p/ o archival)
def record_skill_use(skills_dir, name: str, *, now: float | None = None) -> None:
    """Bump de uso de uma skill (count + last_used) — base do archival LRU. Best-effort, nunca levanta."""
    if not skills_dir or not name:
        return
    p = Path(skills_dir) / USAGE_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        data = {}
    e = data.setdefault(name, {"count": 0, "last_used": 0.0})
    e["count"] = int(e.get("count", 0)) + 1
    e["last_used"] = now if now is not None else time.time()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _usage(skills_dir) -> dict:
    p = Path(skills_dir) / USAGE_FILE
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def is_curatable(skill) -> bool:
    """Só skill AUTO-criada e NÃO pinada. Curada/instalada (sem origin) e pinada → o curator não toca."""
    meta = skill.meta or {}
    if meta.get("pinned"):
        return False
    return str(meta.get("origin", "")) in ("agent", "auto-distilled")


# ---------------------------------------------------------------- snapshot / rollback (reversível)
def snapshot(skills_dir, *, now: float | None = None) -> Path | None:
    """tar.gz de TODAS as skills (menos snapshots) antes de qualquer mutação — rede de segurança."""
    root = Path(skills_dir)
    if not root.exists():
        return None
    snapdir = root / SNAP_DIR
    snapdir.mkdir(parents=True, exist_ok=True)
    # microssegundos: único + ordenável (evita colisão same-second que sobrescrevia o snapshot anterior).
    ts = int((now if now is not None else time.time()) * 1_000_000)
    dest = snapdir / f"skills-{ts}.tgz"
    with tarfile.open(dest, "w:gz") as tar:
        for child in sorted(root.iterdir()):
            if child.name == SNAP_DIR:
                continue                              # não snapshota os próprios snapshots
            tar.add(child, arcname=child.name)
    # mantém os 10 mais recentes (anti-incha)
    for old in sorted(snapdir.glob("skills-*.tgz"))[:-10]:
        old.unlink(missing_ok=True)
    return dest


def rollback(skills_dir) -> Path | None:
    """Restaura o snapshot mais recente. Antes, snapshota o estado atual (rollback é reversível também)."""
    root = Path(skills_dir)
    snapdir = root / SNAP_DIR
    snaps = sorted(snapdir.glob("skills-*.tgz"))
    if not snaps:
        return None
    latest = snaps[-1]
    snapshot(skills_dir)                              # estado atual vira snapshot antes de sobrescrever
    for child in list(root.iterdir()):               # limpa o ativo (menos snapshots)
        if child.name == SNAP_DIR:
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    with tarfile.open(latest, "r:gz") as tar:
        _restore_members(tar, root)
    return latest


def _restore_members(tar, root) -> None:
    """Extrai validando CADA membro contra path-traversal (sem extractall — evita CWE-22). Seguro mesmo
    em Python antigo sem o filtro nativo; e o tar é um snapshot LOCAL nosso, mas validamos assim mesmo."""
    rootp = Path(root).resolve()
    for m in tar.getmembers():
        dest = (rootp / m.name).resolve()
        if dest == rootp or str(dest).startswith(str(rootp) + os.sep):
            try:
                tar.extract(m, root, filter="data")  # 3.12+: filtro nativo (silencia o aviso do 3.14)
            except TypeError:
                tar.extract(m, root)                # 3.11 antigo — já validamos o membro acima


# ---------------------------------------------------------------- archival determinístico (LRU)
def _archive_skill(skills_dir, name: str) -> bool:
    root = Path(skills_dir).resolve()
    src = (root / name).resolve()
    # anti-traversal (audit 2026-06-08): `name='../victim'` / '..' / '/etc' movia/destruía diretório FORA
    # do skills_dir (manage_skill chama isto ANTES de validar o nome). src TEM que ser filho DIRETO de root.
    if src.parent != root or not src.is_dir():
        return False
    dst = root / ARCHIVE_DIR / src.name          # segmento limpo (src.name), nunca o `name` cru
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.move(str(src), str(dst))
    return True


def archival_candidates(skills_dir, *, archive_days: int = 90, now: float | None = None) -> list[str]:
    """Skills AUTO-criadas sem uso há > archive_days (last_used do .usage.json, ou mtime se nunca usada)."""
    from okami.skills import load_skills
    now = now if now is not None else time.time()
    usage = _usage(skills_dir)
    out = []
    for sk in load_skills(Path(skills_dir)):
        if not is_curatable(sk):
            continue
        last = float((usage.get(sk.name) or {}).get("last_used") or 0.0)
        if not last:
            try:
                last = sk.path.stat().st_mtime           # nunca usada → idade do arquivo
            except OSError:
                last = now
        if now - last > archive_days * _DAY:
            out.append(sk.name)
    return out


def archive_unused(skills_dir, *, archive_days: int = 90, now: float | None = None) -> list[str]:
    """Arquiva (move p/ .archive/) as candidatas. Retorna os nomes arquivados."""
    done = []
    for name in archival_candidates(skills_dir, archive_days=archive_days, now=now):
        if _archive_skill(skills_dir, name):
            done.append(name)
    return done


# ---------------------------------------------------------------- pin (intocável pelo curator)
def set_pinned(skills_dir, name: str, pinned: bool) -> bool:
    import yaml as _yaml

    from okami.skills import parse_skill
    f = Path(skills_dir) / name / "SKILL.md"
    if not f.exists():
        return False
    sk = parse_skill(f)
    meta = dict(sk.meta or {})
    if pinned:
        meta["pinned"] = True
    else:
        meta.pop("pinned", None)
    f.write_text("---\n" + _yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n"
                 + sk.body.rstrip() + "\n", encoding="utf-8", newline="\n")
    return True


# ---------------------------------------------------------------- consolidação MODEL-DRIVEN (umbrellas)
_CURATOR_PROMPT = """Você é o CURATOR das suas próprias skills auto-criadas (passada de CONSOLIDAÇÃO em
background, não um audit passivo). Objetivo: uma biblioteca de skills no NÍVEL DE CLASSE — não dezenas
de skills estreitas, cada uma capturando a tarefa de um dia. Centenas de skills de uma-sessão-cada é um
FRACASSO da biblioteca, não um recurso.

Para o conjunto abaixo (só skills auto-criadas; as curadas/pinadas você NÃO vê e NÃO toca):
- FUNDA estreitas/duplicadas numa umbrella de CLASSE: edite a umbrella (manage_skill action=edit) p/
  absorver o conteúdo e ARQUIVE a estreita (manage_skill action=archive).
- ARQUIVE (action=archive) skill de narrativa única / nome de sessão (PR/erro/codinome/"fix-X-hoje").
- Pergunta-guia: "um mantenedor humano escreveria isto como N skills, ou 1 com N seções?" Se 1 → funda.
NUNCA delete (archive é reversível). "Nada a consolidar" é um resultado válido. Ao terminar, task_complete
com 1 linha do que fez.

--- SKILLS AUTO-CRIADAS ---
{skills}
--- FIM ---"""


def agent_skill_digest(skills_dir) -> str:
    from okami.skills import load_skills
    lines = []
    for sk in load_skills(Path(skills_dir)):
        if is_curatable(sk):
            lines.append(f"- {sk.name}: {(sk.description or '')[:80]}")
    return "\n".join(lines) or "(nenhuma)"


def run_consolidation(cfg, workspace, skills_dir, *, model=None, provider=None, emit=lambda m: None) -> None:
    """Forka uma passada model-driven (tools restritas a skill-write) p/ fundir/arquivar. Best-effort."""
    from okami.learning.review import REVIEW_TOOLS
    from okami.runner import run_task
    digest = agent_skill_digest(skills_dir)
    if digest == "(nenhuma)":
        return
    try:
        run_task(cfg, workspace, _CURATOR_PROMPT.format(skills=digest), provider=provider, model=model,
                 skills_dir=skills_dir, registry_filter=REVIEW_TOOLS, approve=lambda req: True,
                 learn=False, surface="review", emit=emit)
    except Exception as e:  # noqa: BLE001
        emit(f"(consolidação falhou: {e})")
