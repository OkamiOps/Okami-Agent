"""Curator COMPLETO (pesquisa #5 item 44) — o que faltava do tier Hermes:

1) lifecycle_pass SEM LLM com estágio intermediário: 30d sem uso → STALE (persistido no
   .usage.json), 90d → ARCHIVE. Antes só existia o archive; stale era derivado on-the-fly.
2) merge model-driven com CONTRATO YAML: o modelo devolve um PLANO (merges/archive) que é
   VALIDADO antes de aplicar — plano inválido → nada muda (fail-closed). Snapshot antes, sempre.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import yaml

from okami.learning import curator as cur

_DAY = 86400.0


def _mk_skill(root: Path, name: str, *, origin="agent", pinned=False, body="## Quando usar\nx\n## Como\ny"):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    meta = {"name": name, "description": f"skill {name}", "origin": origin}
    if pinned:
        meta["pinned"] = True
    (d / "SKILL.md").write_text("---\n" + yaml.safe_dump(meta) + "---\n" + body + "\n", encoding="utf-8")
    return d


def _set_use(root: Path, name: str, *, days_ago: float, now: float):
    p = root / cur.USAGE_FILE
    data = json.loads(p.read_text()) if p.exists() else {}
    data[name] = {"count": 1, "last_used": now - days_ago * _DAY}
    p.write_text(json.dumps(data))


# ------------------------------------------------------------------ lifecycle (sem LLM)
def test_lifecycle_marks_stale_at_30d_persisted(tmp_path):
    now = time.time()
    _mk_skill(tmp_path, "velha")
    _mk_skill(tmp_path, "nova")
    _set_use(tmp_path, "velha", days_ago=45, now=now)
    _set_use(tmp_path, "nova", days_ago=2, now=now)
    out = cur.lifecycle_pass(tmp_path, now=now)
    assert out["stale"] == ["velha"] and out["archived"] == []
    data = json.loads((tmp_path / cur.USAGE_FILE).read_text())
    assert data["velha"]["state"] == "stale"            # persistido, não só derivado
    assert data["nova"]["state"] == "active"


def test_lifecycle_archives_at_90d(tmp_path):
    now = time.time()
    _mk_skill(tmp_path, "morta")
    _set_use(tmp_path, "morta", days_ago=120, now=now)
    out = cur.lifecycle_pass(tmp_path, now=now)
    assert out["archived"] == ["morta"]
    assert not (tmp_path / "morta").exists()            # movida p/ .archive
    assert (tmp_path / cur.ARCHIVE_DIR / "morta").exists()
    data = json.loads((tmp_path / cur.USAGE_FILE).read_text())
    assert data["morta"]["state"] == "archived"


def test_lifecycle_never_touches_pinned_or_curated(tmp_path):
    now = time.time()
    _mk_skill(tmp_path, "fixada", pinned=True)
    _mk_skill(tmp_path, "curada", origin="")            # sem origin agent → instalada/curada
    _set_use(tmp_path, "fixada", days_ago=400, now=now)
    _set_use(tmp_path, "curada", days_ago=400, now=now)
    out = cur.lifecycle_pass(tmp_path, now=now)
    assert out["stale"] == [] and out["archived"] == []
    assert (tmp_path / "fixada").exists() and (tmp_path / "curada").exists()


def test_stale_skill_revives_on_use(tmp_path):
    now = time.time()
    _mk_skill(tmp_path, "zumbi")
    _set_use(tmp_path, "zumbi", days_ago=45, now=now)
    cur.lifecycle_pass(tmp_path, now=now)
    cur.record_skill_use(tmp_path, "zumbi", now=now)    # usada de novo
    out = cur.lifecycle_pass(tmp_path, now=now)
    assert out["stale"] == []
    data = json.loads((tmp_path / cur.USAGE_FILE).read_text())
    assert data["zumbi"]["state"] == "active"


# ------------------------------------------------------------------ contrato YAML do merge
def _plan(**kw):
    base = {"merges": [{"umbrella": "api-debugging", "description": "debug de APIs",
                        "absorb": ["debug-stripe", "debug-github"],
                        "body": "## Quando usar\ndebug de qualquer API\n## Como\n..."}],
            "archive": []}
    base.update(kw)
    return base


def test_validate_plan_accepts_good_plan(tmp_path):
    _mk_skill(tmp_path, "debug-stripe")
    _mk_skill(tmp_path, "debug-github")
    plan, errors = cur.validate_plan(_plan(), tmp_path)
    assert errors == [] and len(plan["merges"]) == 1


def test_validate_plan_rejects_bad_umbrella_and_unknown_absorb(tmp_path):
    _mk_skill(tmp_path, "debug-stripe")
    p = _plan()
    p["merges"][0]["umbrella"] = "Nome Inválido!"
    p["merges"][0]["absorb"] = ["debug-stripe", "nao-existe"]
    _, errors = cur.validate_plan(p, tmp_path)
    assert any("umbrella" in e for e in errors)
    assert any("nao-existe" in e for e in errors)


def test_validate_plan_rejects_pinned_absorb(tmp_path):
    _mk_skill(tmp_path, "fixada", pinned=True)
    p = _plan()
    p["merges"][0]["absorb"] = ["fixada"]
    _, errors = cur.validate_plan(p, tmp_path)
    assert any("fixada" in e for e in errors)


def test_apply_plan_merges_and_archives(tmp_path):
    _mk_skill(tmp_path, "debug-stripe")
    _mk_skill(tmp_path, "debug-github")
    _mk_skill(tmp_path, "lixo-narrativa")
    plan = _plan(archive=["lixo-narrativa"])
    summary = cur.apply_plan(tmp_path, plan)
    assert (tmp_path / "api-debugging" / "SKILL.md").exists()        # umbrella criada
    assert not (tmp_path / "debug-stripe").exists()                  # absorvida → arquivada
    assert (tmp_path / cur.ARCHIVE_DIR / "debug-stripe").exists()
    assert not (tmp_path / "lixo-narrativa").exists()
    assert "api-debugging" in summary["created"]
    snaps = list((tmp_path / cur.SNAP_DIR).glob("skills-*.tgz"))
    assert snaps, "apply_plan tem que snapshotar antes de mutar"


def test_skill_telemetry_separate_view_use_patch(tmp_path):
    # #9: ver / usar / patchear são sinais SEPARADOS (count + timestamp próprios).
    cur.record_skill_use(tmp_path, "s", kind="view", now=100.0)
    cur.record_skill_use(tmp_path, "s", kind="patch", now=200.0)
    cur.record_skill_use(tmp_path, "s", kind="use", now=300.0)
    u = cur._usage(tmp_path)["s"]
    assert u["view_count"] == 1 and u["patch_count"] == 1 and u["count"] == 1
    assert u["last_viewed"] == 100.0 and u["last_patched"] == 200.0 and u["last_used"] == 300.0


def test_archival_uses_latest_activity_across_kinds(tmp_path):
    # skill VISTA recentemente (mas nunca "usada" pelo path exato) NÃO é arquivada injustamente.
    _mk_skill(tmp_path, "s")
    now = 1_000_000_000.0
    cur.record_skill_use(tmp_path, "s", kind="view", now=now - 5 * 86400)   # vista há 5 dias
    assert "s" not in cur.archival_candidates(tmp_path, archive_days=90, now=now)


def test_merge_records_absorbed_names_as_aliases(tmp_path):
    # bug #9: o nome absorvido vira ALIAS na umbrella → `use_skill <nome-antigo>` ainda resolve.
    # Sem isto, um uso/job que cita a skill fundida roda sem as instruções (degradação silenciosa).
    _mk_skill(tmp_path, "debug-stripe")
    _mk_skill(tmp_path, "debug-github")
    cur.apply_plan(tmp_path, _plan())
    from okami.skills import parse_skill
    sk = parse_skill(tmp_path / "api-debugging" / "SKILL.md")
    assert "debug-stripe" in sk.aliases and "debug-github" in sk.aliases


def test_apply_plan_dry_run_mutates_nothing(tmp_path):
    _mk_skill(tmp_path, "debug-stripe")
    _mk_skill(tmp_path, "debug-github")
    cur.apply_plan(tmp_path, _plan(), dry_run=True)
    assert (tmp_path / "debug-stripe").exists()
    assert not (tmp_path / "api-debugging").exists()


# ------------------------------------------------------------------ consolidação fail-closed
def test_consolidation_with_contract_applies_valid_yaml(tmp_path, monkeypatch):
    _mk_skill(tmp_path, "debug-stripe")
    _mk_skill(tmp_path, "debug-github")
    plan_yaml = yaml.safe_dump(_plan(), allow_unicode=True)
    monkeypatch.setattr("okami.llm.aux.aux_complete",
                        lambda cfg, task, msgs, **kw: f"```yaml\n{plan_yaml}\n```")
    out = cur.consolidate_with_contract(None, tmp_path)
    assert out["applied"]
    assert (tmp_path / "api-debugging").exists()


def test_consolidation_invalid_plan_changes_nothing(tmp_path, monkeypatch):
    _mk_skill(tmp_path, "debug-stripe")
    monkeypatch.setattr("okami.llm.aux.aux_complete",
                        lambda cfg, task, msgs, **kw: "merges: [{umbrella: 'X!', absorb: [zzz]}]")
    out = cur.consolidate_with_contract(None, tmp_path)
    assert not out["applied"] and out["errors"]
    assert (tmp_path / "debug-stripe").exists()         # nada mudou (fail-closed)


def test_apply_plan_never_archives_the_umbrella(tmp_path):
    # achado da review #9 (edge pré-existente): plano com umbrella==absorb não pode sumir a umbrella.
    _mk_skill(tmp_path, "foo")
    plan = {"merges": [{"umbrella": "foo", "description": "x", "absorb": ["foo"],
                        "body": "## Quando usar\nx\n## Como\ny"}], "archive": []}
    cur.apply_plan(tmp_path, plan)
    assert (tmp_path / "foo" / "SKILL.md").exists()        # umbrella sobreviveu (não foi arquivada)
