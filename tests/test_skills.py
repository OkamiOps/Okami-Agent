"""Testes do runtime/router de skills (§4.2)."""

from __future__ import annotations

from pathlib import Path

from okami import skills as skillmod

REPO_SKILLS = Path(__file__).resolve().parent.parent / "skills"


def _write(tmp_path, name, triggers, body="corpo da skill"):
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\ntriggers: [{', '.join(triggers)}]\n---\n{body}",
        encoding="utf-8",
    )


def test_parse_and_load(tmp_path):
    _write(tmp_path, "frontend-shadcn", ["shadcn", "ui"])
    sks = skillmod.load_skills(tmp_path)
    assert len(sks) == 1
    assert sks[0].name == "frontend-shadcn"
    assert "shadcn" in sks[0].triggers


def test_route_forces_frontend_skill_by_contract(tmp_path):
    _write(tmp_path, "frontend-shadcn", ["shadcn"])
    sks = skillmod.load_skills(tmp_path)
    contracts = {"ui": {"library": "shadcn"}}
    routed = skillmod.route("Crie um dashboard de vendas", contracts, sks)
    assert [s.name for s in routed] == ["frontend-shadcn"]


def test_route_ignores_when_not_frontend(tmp_path):
    _write(tmp_path, "frontend-shadcn", ["shadcn"])
    sks = skillmod.load_skills(tmp_path)
    routed = skillmod.route("Some os números 2 e 3", {"ui": {"library": "shadcn"}}, sks)
    assert routed == []


def test_repo_ships_frontend_skills():
    names = {s.name for s in skillmod.load_skills(REPO_SKILLS)}
    assert {"frontend-shadcn", "frontend-heroui"} <= names


def test_repo_ships_bundled_skills():
    names = {s.name for s in skillmod.load_skills(REPO_SKILLS)}
    assert {"humanizer", "proactive-agent", "tdd", "writing-plans", "communication-131"} <= names


def test_catalog_lists_and_excludes(tmp_path):
    _write(tmp_path, "frontend-shadcn", ["shadcn"])
    _write(tmp_path, "humanizer", ["humanizar"])
    cat = skillmod.catalog(skillmod.load_skills(tmp_path), exclude={"frontend-shadcn"})
    assert "humanizer:" in cat and "use_skill" in cat
    assert "frontend-shadcn:" not in cat


def test_use_skill_tool_loads_body():
    from pathlib import Path

    from okami.core.tools import ToolContext, UseSkill

    ctx = ToolContext(workspace=Path("."), skills={"humanizer": "corpo da skill humanizer"})
    ok = UseSkill().run({"name": "humanizer"}, ctx)
    assert ok.ok and "corpo da skill humanizer" in ok.output
    assert not UseSkill().run({"name": "inexistente"}, ctx).ok


def test_render_block_marks_mandatory(tmp_path):
    _write(tmp_path, "frontend-shadcn", ["shadcn"])
    block = skillmod.render_block(skillmod.load_skills(tmp_path))
    assert "OBRIGAT" in block.upper() and "frontend-shadcn" in block
