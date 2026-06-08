"""Curator — tier lento, REVERSÍVEL, de consolidação das skills auto-criadas (estilo Hermes).

Cobre: LRU (uso protege do archival), provenance (só auto-criada; curada/pinada intocável), archival
determinístico + .archive fora do catálogo, snapshot/rollback, pin, manage_skill archive, e o CLI."""

from __future__ import annotations

import os
import time

from typer.testing import CliRunner

from okami.cli import app
from okami.learning import curator as cur
from okami.skills import load_skills

runner = CliRunner()
OLD = 200 * 86400


def _mk(root, name, *, origin=None, pinned=False, age_days=0):
    d = root / name
    d.mkdir(parents=True)
    fm = f"---\nname: {name}\ndescription: d\n"
    fm += f"origin: {origin}\n" if origin else ""
    fm += "pinned: true\n" if pinned else ""
    f = d / "SKILL.md"
    f.write_text(fm + "---\n## Como\nconteúdo suficiente\n", encoding="utf-8")
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(f, (t, t))


def _seed(root):
    _mk(root, "agent-old", origin="agent", age_days=200)         # auto, velha, sem uso → arquiva
    _mk(root, "auto-old", origin="auto-distilled", age_days=200)  # idem (origem mecânica legada)
    _mk(root, "agent-pinned", origin="agent", pinned=True, age_days=200)  # pinada → fica
    _mk(root, "curated", age_days=200)                            # sem origin (curada/instalada) → fica
    _mk(root, "agent-fresh", origin="agent", age_days=1)          # recente → fica


def test_is_curatable_only_auto_and_unpinned(tmp_path):
    _seed(tmp_path)
    by = {s.name: s for s in load_skills(tmp_path)}
    assert cur.is_curatable(by["agent-old"]) and cur.is_curatable(by["auto-old"])
    assert not cur.is_curatable(by["agent-pinned"])   # pinada
    assert not cur.is_curatable(by["curated"])        # sem origin


def test_archival_candidates_lru_and_provenance(tmp_path):
    _seed(tmp_path)
    cands = set(cur.archival_candidates(tmp_path, archive_days=90))
    assert cands == {"agent-old", "auto-old"}         # só auto + velha + sem uso; pinada/curada/fresca fora
    # uso recente PROTEGE do archival (LRU)
    cur.record_skill_use(tmp_path, "agent-old")
    assert "agent-old" not in set(cur.archival_candidates(tmp_path, archive_days=90))


def test_archive_unused_moves_out_of_catalog(tmp_path):
    _seed(tmp_path)
    archived = set(cur.archive_unused(tmp_path, archive_days=90))
    assert archived == {"agent-old", "auto-old"}
    active = {s.name for s in load_skills(tmp_path)}
    assert "agent-old" not in active and "auto-old" not in active   # .archive não volta ao catálogo
    assert {"agent-pinned", "curated", "agent-fresh"} <= active
    assert (tmp_path / ".archive" / "agent-old" / "SKILL.md").exists()  # arquivada, NÃO deletada


def test_snapshot_and_rollback_restores(tmp_path):
    _seed(tmp_path)
    cur.snapshot(tmp_path)
    cur.archive_unused(tmp_path, archive_days=90)
    assert "agent-old" not in {s.name for s in load_skills(tmp_path)}
    cur.rollback(tmp_path)
    assert "agent-old" in {s.name for s in load_skills(tmp_path)}   # voltou


def test_set_pinned_exempts(tmp_path):
    _mk(tmp_path, "agent-old", origin="agent", age_days=200)
    assert cur.archival_candidates(tmp_path, archive_days=90) == ["agent-old"]
    cur.set_pinned(tmp_path, "agent-old", True)
    assert cur.archival_candidates(tmp_path, archive_days=90) == []  # pinada → não arquiva


def test_manage_skill_archive_action(tmp_path):
    from okami.core.tools import ManageSkill, ToolContext
    _mk(tmp_path / "skills", "agent-x", origin="agent")
    ctx = ToolContext(workspace=tmp_path, skills_dir=tmp_path / "skills")
    r = ManageSkill().run({"action": "archive", "name": "agent-x"}, ctx)
    assert r.ok and (tmp_path / "skills" / ".archive" / "agent-x").exists()
    assert not (tmp_path / "skills" / "agent-x").exists()


def test_run_consolidation_forks_restricted(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import okami.runner as runner_mod
    from okami.core import Task
    from okami.learning.review import REVIEW_TOOLS
    _mk(tmp_path, "agent-a", origin="agent")
    seen = {}

    def fake_run_task(cfg, ws, goal, **kw):
        seen.update(goal=goal, **kw)
        return Task(goal=goal)
    monkeypatch.setattr(runner_mod, "run_task", fake_run_task)
    cur.run_consolidation(SimpleNamespace(), ".", tmp_path)
    assert seen["registry_filter"] == REVIEW_TOOLS and seen["learn"] is False
    assert "umbrella" in seen["goal"].lower() and "agent-a" in seen["goal"]


# ----------------------------------------------------------------- CLI
def test_curator_cli_dry_run_and_real(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setattr("okami.home.skills_dir", lambda: tmp_path)
    # dry-run: lista candidata, NÃO arquiva
    res = runner.invoke(app, ["curator", "--dry-run"])
    assert res.exit_code == 0 and "agent-old" in res.output
    assert "agent-old" in {s.name for s in load_skills(tmp_path)}
    # real, sem LLM: arquiva determinístico + snapshot
    res = runner.invoke(app, ["curator", "--no-llm", "--yes"])
    assert res.exit_code == 0
    assert "agent-old" not in {s.name for s in load_skills(tmp_path)}
    # rollback restaura
    res = runner.invoke(app, ["curator", "rollback"])
    assert res.exit_code == 0 and "agent-old" in {s.name for s in load_skills(tmp_path)}


def test_curator_cli_pin(tmp_path, monkeypatch):
    _mk(tmp_path, "agent-old", origin="agent", age_days=200)
    monkeypatch.setattr("okami.home.skills_dir", lambda: tmp_path)
    runner.invoke(app, ["curator", "pin", "agent-old"])
    res = runner.invoke(app, ["curator", "--no-llm", "--yes"])
    assert res.exit_code == 0
    assert "agent-old" in {s.name for s in load_skills(tmp_path)}    # pinada sobreviveu
