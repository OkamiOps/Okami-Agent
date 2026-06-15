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
import re
import shutil
import tarfile
import time
from pathlib import Path

USAGE_FILE = ".usage.json"
ARCHIVE_DIR = ".archive"
SNAP_DIR = ".snapshots"
_DAY = 86400.0


# ---------------------------------------------------------------- uso (LRU telemetry, p/ o archival)
# #9: sinais SEPARADOS de atividade da skill — (count_field, ts_field) por kind. Ver≠usar≠patchear:
# uma skill muito VISTA e nunca "usada" pelo path exato, ou só patchada, não pode ser arquivada como morta.
_ACTIVITY_FIELDS = {"use": ("count", "last_used"), "view": ("view_count", "last_viewed"),
                    "patch": ("patch_count", "last_patched")}


def _latest_activity(entry: dict) -> float:
    """Maior timestamp entre use/view/patch — o relógio REAL de atividade da skill (anti-archival injusto)."""
    return max(float(entry.get("last_used") or 0.0), float(entry.get("last_viewed") or 0.0),
               float(entry.get("last_patched") or 0.0))


def record_skill_use(skills_dir, name: str, *, kind: str = "use", now: float | None = None) -> None:
    """Bump de atividade de uma skill. kind=use|view|patch (count + timestamp próprios). Base do archival
    (que usa o MAX dos três). Best-effort, nunca levanta."""
    if not skills_dir or not name:
        return
    cf, tf = _ACTIVITY_FIELDS.get(kind, _ACTIVITY_FIELDS["use"])
    p = Path(skills_dir) / USAGE_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        data = {}
    e = data.setdefault(name, {"count": 0, "last_used": 0.0})
    e[cf] = int(e.get(cf, 0)) + 1
    e[tf] = now if now is not None else time.time()
    e.setdefault("state", "active")          # qualquer atividade revive: não fica 'stale' enquanto é tocada
    if e.get("state") == "stale":
        e["state"] = "active"
    _write_usage_atomic(p, data)


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
        last = _latest_activity(usage.get(sk.name) or {})   # #9: max(use, view, patch) — não só last_used
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


def _write_usage_atomic(p: Path, data: dict) -> None:
    """Escrita ATÔMICA do .usage.json (tmp + os.replace): um crash no meio não trunca o arquivo
    (era write_text cru — bug do review #8). Best-effort."""
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass


def _set_state(skills_dir, name: str, state: str) -> None:
    """Persiste o estado de lifecycle no .usage.json (best-effort, escrita atômica)."""
    p = Path(skills_dir) / USAGE_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        data = {}
    data.setdefault(name, {"count": 0, "last_used": 0.0})["state"] = state
    _write_usage_atomic(p, data)


def lifecycle_pass(skills_dir, *, stale_days: int = 30, archive_days: int = 90,
                   now: float | None = None) -> dict:
    """Passada de LIFECYCLE pura (sem LLM, pesquisa #5 item 44 — tier semanal do Hermes):
    30d sem uso → STALE (persistido no .usage.json; skill usada de novo volta a active),
    90d → ARCHIVE (move p/ .archive/, reversível). Só toca skill auto-criada e não-pinada.
    Retorna {"active": [...], "stale": [...], "archived": [...]}."""
    from okami.skills import load_skills
    now = now if now is not None else time.time()
    usage = _usage(skills_dir)
    out: dict[str, list[str]] = {"active": [], "stale": [], "archived": []}
    for sk in load_skills(Path(skills_dir)):
        if not is_curatable(sk):
            continue
        last = _latest_activity(usage.get(sk.name) or {})   # #9: max(use, view, patch) — não só last_used
        if not last:
            try:
                last = sk.path.stat().st_mtime           # nunca usada → idade do arquivo
            except OSError:
                last = now
        idle = now - last
        if idle > archive_days * _DAY:
            if _archive_skill(skills_dir, sk.name):
                _set_state(skills_dir, sk.name, "archived")
                out["archived"].append(sk.name)
            continue
        state = "stale" if idle > stale_days * _DAY else "active"
        _set_state(skills_dir, sk.name, state)
        out[state].append(sk.name)
    return out


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


# ---------------------------------------------------------------- merge com CONTRATO YAML (item 44)
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,47}$")   # mesmo contrato do manage_skill
_YAML_FENCE = re.compile(r"```(?:ya?ml)?\s*(.*?)```", re.DOTALL)

_PLAN_PROMPT = """Você é o CURATOR das skills auto-criadas. Proponha um PLANO de consolidação:
funda skills estreitas/duplicadas numa umbrella de CLASSE e arquive narrativa de sessão única.
"Centenas de skills estreitas = FRACASSO da biblioteca." "Nada a consolidar" é resposta válida
(devolva merges: [] e archive: []).

Responda APENAS com YAML neste contrato (nada fora do YAML):

merges:
  - umbrella: <nome-kebab-de-classe>
    description: <1 linha>
    absorb: [<skill-existente>, ...]
    body: |
      ## Quando usar
      ...
      ## Como
      ...
archive: [<skill-de-narrativa-unica>, ...]

--- SKILLS AUTO-CRIADAS ---
{skills}
--- FIM ---"""


def validate_plan(plan, skills_dir) -> tuple[dict, list[str]]:
    """Valida o plano contra o CONTRATO antes de aplicar (fail-closed). Retorna (plano_normalizado,
    erros). Erros ≠ [] → NÃO aplique. Regras: umbrella kebab nível-classe; absorb/archive só skills
    EXISTENTES e curáveis (auto-criadas, não-pinadas); body de umbrella com substância (≥20 chars)."""
    from okami.skills import load_skills
    errors: list[str] = []
    if not isinstance(plan, dict):
        return {"merges": [], "archive": []}, ["plano não é um mapeamento YAML"]
    all_skills = load_skills(Path(skills_dir))
    curatable = {sk.name for sk in all_skills if is_curatable(sk)}
    protected = {sk.name for sk in all_skills if not is_curatable(sk)}   # pinada/curada/instalada
    norm: dict = {"merges": [], "archive": []}
    for i, m in enumerate(plan.get("merges") or []):
        if not isinstance(m, dict):
            errors.append(f"merges[{i}]: não é um mapeamento")
            continue
        umb = str(m.get("umbrella", "")).strip()
        if not _NAME_RE.match(umb) or umb.count("-") > 3:
            errors.append(f"merges[{i}]: umbrella inválida ({umb!r}) — kebab-case curto, nível de classe")
        elif umb in protected:                         # umbrella não pode sobrescrever skill protegida (#9)
            errors.append(f"merges[{i}]: umbrella '{umb}' colide com skill protegida (pinada/curada) — "
                          "escolha outro nome")
        absorb = [str(a).strip() for a in (m.get("absorb") or [])]
        if not absorb:
            errors.append(f"merges[{i}]: absorb vazio — umbrella sem skills a fundir")
        for a in absorb:
            if a not in curatable:
                errors.append(f"merges[{i}]: '{a}' não existe ou não é curável (pinada/curada)")
        body = str(m.get("body", "")).strip()
        if len(body) < 20:
            errors.append(f"merges[{i}]: body curto demais — escreva o procedimento da umbrella")
        norm["merges"].append({"umbrella": umb, "description": str(m.get("description", umb))[:120],
                               "absorb": absorb, "body": body})
    for a in (plan.get("archive") or []):
        a = str(a).strip()
        if a not in curatable:
            errors.append(f"archive: '{a}' não existe ou não é curável (pinada/curada)")
        norm["archive"].append(a)
    return norm, errors


def apply_plan(skills_dir, plan, *, dry_run: bool = False) -> dict:
    """Aplica um plano JÁ VALIDADO: snapshot → escreve umbrellas (origin: agent) → arquiva absorvidas
    + archive (reversível). dry_run = só reporta. Retorna {"created": [...], "archived": [...]}."""
    import yaml as _yaml
    _umbrellas = {m["umbrella"] for m in (plan.get("merges") or [])}
    summary = {"created": [m["umbrella"] for m in plan.get("merges") or []],
               # #9 review: NUNCA arquiva a própria umbrella (plano com umbrella==absorb sumia a umbrella).
               "archived": sorted(({a for m in (plan.get("merges") or []) for a in m["absorb"]}
                                  | set(plan.get("archive") or [])) - _umbrellas)}
    if dry_run:
        return summary
    snapshot(skills_dir)
    root = Path(skills_dir)
    for m in plan.get("merges") or []:
        d = root / m["umbrella"]
        d.mkdir(parents=True, exist_ok=True)
        meta = {"name": m["umbrella"], "description": m["description"], "origin": "agent",
                "merged_from": list(m["absorb"]),      # proveniência do merge (auditável)
                # bug #9: o nome absorvido vira ALIAS → `use_skill <nome-antigo>` ainda resolve p/ a
                # umbrella (senão um uso/job que cita a skill fundida roda sem as instruções).
                "aliases": list(m["absorb"])}
        (d / "SKILL.md").write_text("---\n" + _yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
                                    + "---\n" + m["body"].rstrip() + "\n", encoding="utf-8", newline="\n")
    for name in summary["archived"]:
        if _archive_skill(skills_dir, name):
            _set_state(skills_dir, name, "archived")
    return summary


def consolidate_with_contract(cfg, skills_dir, *, dry_run: bool = False, emit=lambda m: None) -> dict:
    """Merge model-driven FAIL-CLOSED: pede o PLANO (YAML) ao modelo auxiliar (task 'curator'),
    valida contra o contrato e só aplica se passar. Plano inválido/YAML quebrado → nada muda.
    Retorna {"applied": bool, "errors": [...], "summary": {...}}."""
    import yaml as _yaml
    digest = agent_skill_digest(skills_dir)
    if digest == "(nenhuma)":
        return {"applied": False, "errors": [], "summary": {}}
    from okami.llm.aux import aux_complete
    try:
        out = aux_complete(cfg, "curator", [{"role": "user", "content": _PLAN_PROMPT.format(skills=digest)}])
    except Exception as e:  # noqa: BLE001 — LLM indisponível → passada pulada, nada muda
        emit(f"(consolidação pulada: {e})")
        return {"applied": False, "errors": [str(e)], "summary": {}}
    raw = (out or "").strip()
    fence = _YAML_FENCE.search(raw)
    if fence:
        raw = fence.group(1)
    try:
        plan = _yaml.safe_load(raw) or {}
    except _yaml.YAMLError as e:
        emit(f"(plano YAML inválido: {e})")
        return {"applied": False, "errors": [f"YAML inválido: {e}"], "summary": {}}
    norm, errors = validate_plan(plan, skills_dir)
    if errors:
        emit("(plano reprovado no contrato: " + "; ".join(errors[:3]) + ")")
        return {"applied": False, "errors": errors, "summary": {}}
    if not norm["merges"] and not norm["archive"]:
        return {"applied": False, "errors": [], "summary": {}}      # "nada a consolidar" é válido
    summary = apply_plan(skills_dir, norm, dry_run=dry_run)
    return {"applied": not dry_run, "errors": [], "summary": summary}


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
