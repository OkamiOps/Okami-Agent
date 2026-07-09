"""Skill nativa `frontend-design` — a flagship de frontend do Okami (dono: maior parte do trabalho é
construir frontend, então isto tem que ser genuinamente bom, não um stub). Cobre: parseia via
`load_builtin_skills`, tem os campos de frontmatter esperados (name/description/triggers/
intent_examples), passa limpo no security scan (senão `with_builtin` a descarta silenciosamente) e
aparece no catálogo."""
from __future__ import annotations

from okami.builtin import builtin_skills_root
from okami.skills import catalog, load_builtin_skills
from okami.skills.skill_security import scan_path

ROOT = builtin_skills_root()
SKILL_NAME = "frontend-design"


def test_frontend_design_parses_with_expected_frontmatter():
    bs = {s.name: s for s in load_builtin_skills()}
    assert SKILL_NAME in bs, "skill frontend-design não carregou via load_builtin_skills"
    sk = bs[SKILL_NAME]
    assert sk.name == SKILL_NAME
    assert sk.description, "skill sem description"
    assert sk.triggers, "skill sem triggers"
    assert sk.intent_examples, "skill sem intent_examples"
    # triggers cobrem os principais gatilhos de frontend em pt-BR/en
    assert any(t in sk.triggers for t in ("frontend", "ui", "landing", "dashboard"))


def test_frontend_design_scans_clean():
    report = scan_path(ROOT / SKILL_NAME)
    assert not report.blocked, [str(f) for f in report.sorted()]


def test_frontend_design_appears_in_builtin_catalog():
    bs = load_builtin_skills()
    names = {s.name for s in bs}
    assert SKILL_NAME in names
    sk = next(s for s in bs if s.name == SKILL_NAME)
    cat = catalog([sk])
    assert SKILL_NAME in cat
    assert sk.description[:20] in cat


def test_frontend_design_covers_core_sections():
    text = (ROOT / SKILL_NAME / "SKILL.md").read_text(encoding="utf-8")
    for marker in (
        "Tipografia",
        "Cor",
        "Layout",
        "Motion",
        "Responsivo",
        "Checklist",
        "cara de IA",
    ):
        assert marker in text, f"seção esperada ausente: {marker}"


def test_frontend_design_cross_references_library_skills_without_duplicating():
    text = (ROOT / SKILL_NAME / "SKILL.md").read_text(encoding="utf-8")
    assert "frontend-heroui" in text
    assert "frontend-shadcn" in text
    assert "generate_pdf" in text


def test_frontend_design_estilos_do_marcos_reference_exists_and_is_referenced():
    """Referência dos 10 sites de demonstração do dono (dez direções de arte reais e validadas,
    não templates especulativos) — precisa existir, ser citada no SKILL.md via
    ${OKAMI_SKILL_DIR}/references/... (progressive disclosure) e cobrir os 10 nomes de estilo para
    que o agente consiga reconhecer o pedido ("faz no estilo Lumen", "quero algo tipo MONOLITH")."""
    ref_path = ROOT / SKILL_NAME / "references" / "estilos-do-marcos.md"
    assert ref_path.is_file(), f"referência ausente: {ref_path}"
    ref_text = ref_path.read_text(encoding="utf-8")

    skill_text = (ROOT / SKILL_NAME / "SKILL.md").read_text(encoding="utf-8")
    assert "references/estilos-do-marcos.md" in skill_text, (
        "SKILL.md não aponta para a referência dos 10 estilos (progressive disclosure via "
        "${OKAMI_SKILL_DIR})"
    )
    assert "${OKAMI_SKILL_DIR}" in skill_text

    style_names = (
        "MONOLITH",
        "Lumen",
        "Coerência",
        "FORJA Compute",
        "Kinetic Labs",
        "Hélice",
        "Vitalis",
        "Agent Smith",
        "Lionclaw",
    )
    for name in style_names:
        assert name in ref_text, f"referência não menciona o estilo {name!r}"
    # Lionclaw aparece duas vezes (09 editorial, 10 grid) — confirma que ambos os conceitos
    # estão documentados, não só o nome da marca uma vez.
    assert ref_text.count("Lionclaw") >= 2

    # capta a essência/taste do dono em termos concretos: hex reais e famílias de fonte reais,
    # não descrição vaga.
    assert "#" in ref_text and ref_text.count("#") > 20
    for font in ("JetBrains Mono", "Fraunces", "Hanken Grotesk"):
        assert font in ref_text


def test_frontend_design_dir_still_scans_clean_with_new_reference():
    report = scan_path(ROOT / SKILL_NAME)
    assert not report.blocked, [str(f) for f in report.sorted()]
