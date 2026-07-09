"""5 skills de desenvolvimento portadas do Hermes (software-development/{simplify-code,spike,
requesting-code-review,python-debugpy} + github/codebase-inspection) — só orientação (SKILL.md
puro, sem scripts). Cobre: carrega via `load_builtin_skills`, aparece no catálogo, tem frontmatter
obrigatório (name/description/triggers), e passa limpo no security scan (senão `with_builtin`
descarta a skill sem avisar)."""
from __future__ import annotations

from okami.builtin import builtin_skills_root
from okami.skills import catalog, load_builtin_skills
from okami.skills.skill_security import scan_path

ROOT = builtin_skills_root()

PORTED_CODING_SKILLS = (
    "simplify-code",
    "spike",
    "requesting-code-review",
    "python-debug",
    "codebase-inspection",
)


def test_all_present_on_disk():
    for name in PORTED_CODING_SKILLS:
        skill_md = ROOT / name / "SKILL.md"
        assert skill_md.is_file(), f"{name}/SKILL.md missing"


def test_all_load_via_load_builtin_skills():
    bs = {s.name: s for s in load_builtin_skills()}
    for name in PORTED_CODING_SKILLS:
        assert name in bs, f"{name} not found among builtin skills"


def test_all_have_required_frontmatter():
    bs = {s.name: s for s in load_builtin_skills()}
    for name in PORTED_CODING_SKILLS:
        sk = bs[name]
        assert sk.name == name
        assert sk.description, f"{name} missing description"
        assert sk.triggers, f"{name} should declare triggers"
        assert sk.intent_examples, f"{name} should declare intent_examples"
        assert sk.body, f"{name} body is empty"


def test_all_appear_in_catalog():
    bs = {s.name: s for s in load_builtin_skills()}
    skills = [bs[name] for name in PORTED_CODING_SKILLS]
    cat = catalog(skills)
    for name in PORTED_CODING_SKILLS:
        assert name in cat
        assert bs[name].description[:20] in cat


def test_all_scan_clean():
    # Nativas DEVEM passar limpo no scan — senão with_builtin descarta a skill sem avisar.
    for name in PORTED_CODING_SKILLS:
        report = scan_path(ROOT / name)
        assert not report.blocked, [str(f) for f in report.sorted()]


def test_ported_from_metadata_points_to_hermes_source():
    bs = {s.name: s for s in load_builtin_skills()}
    for name in PORTED_CODING_SKILLS:
        meta = bs[name].meta.get("metadata", {}).get("hermes", {})
        assert meta.get("ported_from", "").startswith("hermes-agent/skills/"), name
