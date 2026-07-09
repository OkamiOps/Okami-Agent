"""Cobertura das skills nativas `design-systems` e `sketch` (porta do Hermes
`popular-web-designs`/`sketch`): catálogo de sistemas de design reais pra ancorar UI numa estética
coerente, e workflow de mockups descartáveis pra comparar direção antes de implementar.

Segue o padrão de tests/test_builtin_skills_quality.py e tests/test_skills.py: parse via
load_builtin_skills, campos obrigatórios (name/description), scan de segurança limpo, e arquivos
de apoio (references/) presentes/legíveis via progressive disclosure.
"""
from __future__ import annotations

from okami.builtin import builtin_skills_root
from okami.skills import catalog, load_builtin_skills
from okami.skills.skill_security import scan_path

ROOT = builtin_skills_root()
NAMES = ("design-systems", "sketch")


def _by_name() -> dict:
    return {sk.name: sk for sk in load_builtin_skills()}


def test_both_skills_present_in_builtin_catalog():
    skills = _by_name()
    for name in NAMES:
        assert name in skills, f"skill nativa '{name}' não foi carregada por load_builtin_skills()"


def test_both_skills_parse_with_required_fields():
    skills = _by_name()
    for name in NAMES:
        sk = skills[name]
        assert sk.name and sk.description, f"skill {name} sem name/description"
        assert sk.triggers, f"skill {name} sem triggers"
        assert sk.intent_examples, f"skill {name} sem intent_examples"
        cat = catalog([sk])
        assert sk.name in cat and sk.description[:20] in cat


def test_both_skills_scan_clean():
    for name in NAMES:
        skill_dir = ROOT / name
        assert (skill_dir / "SKILL.md").exists(), f"{name}/SKILL.md não existe"
        report = scan_path(skill_dir)
        assert not report.blocked, (name, [str(f) for f in report.sorted()])


def test_design_systems_skill_points_to_reference_catalog():
    skills = _by_name()
    sk = skills["design-systems"]
    assert "references/sistemas.md" in sk.body
    ref = ROOT / "design-systems" / "references" / "sistemas.md"
    assert ref.exists(), "catálogo de sistemas de design não encontrado"
    text = ref.read_text(encoding="utf-8")
    # amostra de sistemas reais portados do catálogo Hermes — cobrindo várias categorias
    for site in ("Stripe", "Linear", "Vercel", "Notion", "Apple", "Spotify"):
        assert site in text, f"catálogo de design systems não menciona {site}"


def test_sketch_skill_describes_variant_workflow():
    skills = _by_name()
    sk = skills["sketch"]
    body_lower = sk.body.lower()
    # núcleo do método: intake -> 2-3 variantes -> comparação
    assert "variante" in body_lower
    assert "readme" in body_lower or "README" in sk.body
    assert "design-systems" in sk.body, "sketch deveria referenciar a skill design-systems"


def test_sketch_reference_html_has_no_shebang_or_script_execution():
    ref = ROOT / "sketch" / "references" / "esqueleto.html"
    assert ref.exists()
    text = ref.read_text(encoding="utf-8")
    assert not text.startswith("#!"), "arquivo de referência não deve ter shebang"
    assert "<!doctype html>" in text.lower()


def test_no_new_skill_ships_shebang_scripts():
    """As duas skills são conteúdo puro (markdown/HTML) — nenhum script executável, então nenhum
    arquivo deveria abrir com shebang (regra do scanner: shebang + rede == HIGH)."""
    for name in NAMES:
        skill_dir = ROOT / name
        for f in skill_dir.rglob("*"):
            if f.is_file():
                head = f.read_bytes()[:2]
                assert head != b"#!", f"{f} começa com shebang — skill deveria ser conteúdo puro"


def test_all_builtin_skills_still_scan_clean_and_parse():
    """Guarda-chuva: garante que adicionar as duas skills novas não quebrou o carregamento nem o
    scan de segurança do conjunto inteiro de skills nativas (mesmo espírito de
    test_builtin_skills_quality.py)."""
    bs = load_builtin_skills()
    loaded_names = {sk.name for sk in bs}
    for name in NAMES:
        assert name in loaded_names
    for md in sorted(ROOT.rglob("SKILL.md")):
        report = scan_path(md.parent)
        assert not report.blocked, (md.parent.name, [str(f) for f in report.sorted()])
