"""Skills PORTADAS de skills.sh (fontes reais: vercel-labs/agent-skills, nextlevelbuilder/ui-ux-pro-max-
skill, leonxlnx/taste-skill, shadcn-ui/ui, heygen-com/hyperframes) — 8 skills de frontend/design/vídeo que
faltavam no catálogo nativo. Cobre: cada skill carrega via `load_builtin_skills`/`catalog`, aparece com
nome+descrição+triggers, passa limpo (HIGH/CRITICAL zero) no security scan — senão `with_builtin` a
descarta silenciosamente do catálogo do usuário — e os arquivos de apoio (references/rules/adapters/data)
citados no corpo da skill existem em disco."""
from __future__ import annotations

from okami.builtin import builtin_skills_root
from okami.skills import catalog, load_builtin_skills
from okami.skills.skill_security import Severity, scan_path

ROOT = builtin_skills_root()

PORTED = (
    "web-design-guidelines",
    "vercel-react-best-practices",
    "ui-ux-pro-max",
    "design-taste-frontend",
    "shadcn",
    "hyperframes",
    "hyperframes-creative",
    "hyperframes-animation",
)


def test_all_ported_skills_load_with_expected_fields():
    bs = {s.name: s for s in load_builtin_skills()}
    for name in PORTED:
        assert name in bs, f"{name} not found among builtin skills"
        sk = bs[name]
        assert sk.name == name
        assert sk.description, f"{name} missing description"
        assert sk.triggers, f"{name} should declare triggers (Okami frontmatter convention)"
        assert sk.intent_examples, f"{name} should declare intent_examples"
        cat = catalog([sk])
        assert name in cat and sk.description[:20] in cat


def test_all_ported_skills_scan_clean():
    # Segurança CRÍTICA: HIGH/CRITICAL bloqueiam a skill silenciosamente do catálogo do usuário
    # (with_builtin descarta sem avisar) — então isto é o contrato mínimo, não um nice-to-have.
    for name in PORTED:
        report = scan_path(ROOT / name)
        assert not report.blocked, [str(f) for f in report.sorted()]
        assert report.max_severity < Severity.HIGH


def test_web_design_guidelines_reference_present():
    ref = ROOT / "web-design-guidelines" / "references" / "web-interface-guidelines.md"
    assert ref.is_file()
    text = ref.read_text(encoding="utf-8")
    assert "aria-label" in text and "prefers-reduced-motion" in text


def test_vercel_react_best_practices_full_ruleset_present():
    ref = ROOT / "vercel-react-best-practices" / "references" / "AGENTS.md"
    assert ref.is_file()
    text = ref.read_text(encoding="utf-8")
    for heading in ("Eliminating Waterfalls", "Bundle Size Optimization",
                     "Re-render Optimization", "JavaScript Performance"):
        assert heading in text
    sk_text = (ROOT / "vercel-react-best-practices" / "SKILL.md").read_text(encoding="utf-8")
    for rule in ("async-parallel", "bundle-barrel-imports", "rerender-memo", "js-early-exit"):
        assert rule in sk_text


def test_ui_ux_pro_max_search_tool_and_data_present():
    root = ROOT / "ui-ux-pro-max"
    for script in ("core.py", "design_system.py", "search.py"):
        assert (root / "scripts" / script).is_file()
    for data_file in ("colors.csv", "typography.csv", "products.csv", "ux-guidelines.csv"):
        assert (root / "data" / data_file).is_file()
    assert (root / "data" / "stacks" / "nextjs.csv").is_file()
    assert (root / "data" / "stacks" / "shadcn.csv").is_file()


def test_ui_ux_pro_max_search_script_imports_cleanly():
    # Não executamos o script (evita rede/efeitos colaterais em CI) — só garantimos que a estrutura
    # de import (core.py ao lado, DATA_DIR relativo a scripts/../data) resolve sem crashar no import.
    import importlib.util
    import sys

    scripts_dir = ROOT / "ui-ux-pro-max" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        spec = importlib.util.spec_from_file_location("_uxm_core_test", scripts_dir / "core.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.DATA_DIR == (scripts_dir.parent / "data")
        assert mod.DATA_DIR.is_dir()
    finally:
        sys.path.remove(str(scripts_dir))
        sys.modules.pop("_uxm_core_test", None)


def test_design_taste_frontend_is_self_contained_and_substantial():
    sk_path = ROOT / "design-taste-frontend" / "SKILL.md"
    text = sk_path.read_text(encoding="utf-8")
    assert len(text.splitlines()) > 500
    assert "BRIEF INFERENCE" in text


def test_shadcn_rules_files_present():
    root = ROOT / "shadcn"
    for f in ("cli.md", "customization.md", "registry.md"):
        assert (root / f).is_file()
    for f in ("styling.md", "forms.md", "composition.md", "icons.md", "chat.md", "base-vs-radix.md"):
        assert (root / "rules" / f).is_file()


def test_hyperframes_router_lists_domain_skills():
    text = (ROOT / "hyperframes" / "SKILL.md").read_text(encoding="utf-8")
    assert "hyperframes-animation" in text and "hyperframes-creative" in text


def test_hyperframes_creative_references_and_palettes_present():
    root = ROOT / "hyperframes-creative"
    for f in ("house-style.md", "video-composition.md", "typography.md", "design-spec.md"):
        assert (root / "references" / f).is_file()
    palette_files = list((root / "palettes").glob("*.md"))
    assert len(palette_files) >= 9


def test_hyperframes_animation_index_and_adapters_present():
    root = ROOT / "hyperframes-animation"
    for f in ("rules-index.md", "blueprints-index.md", "techniques.md"):
        assert (root / f).is_file()
    for f in ("gsap.md", "lottie.md", "three.md", "animejs.md", "css-animations.md", "waapi.md", "typegpu.md"):
        assert (root / "adapters" / f).is_file()
    assert (root / "transitions" / "overview.md").is_file()
    assert (root / "transitions" / "catalog.md").is_file()
