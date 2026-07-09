"""Biblioteca de referência implementation-grade dos 10 estilos do Marcos, dentro da skill
`frontend-design`. Antes só existia um resumo de taste (`estilos-do-marcos.md`); agora cada estilo
tem um arquivo de detalhe com `:root` exato, técnica-assinatura em código real e postura de
hero/3D, mais um arquivo de técnicas transversais — para o agente CONSTRUIR os sites, não só
descrevê-los. Cobre: os 10 arquivos de detalhe existem e são apontados pelo índice, o arquivo de
técnicas transversais existe e documenta a dicotomia protagonista-vs-ambiente, o SKILL.md explica
o fluxo índice→detalhe, e a skill inteira (com os novos arquivos) continua parseando e passando
limpo no security scan."""
from __future__ import annotations

from okami.builtin import builtin_skills_root
from okami.skills import load_builtin_skills
from okami.skills.skill_security import scan_path

ROOT = builtin_skills_root()
SKILL_NAME = "frontend-design"
REF_DIR = ROOT / SKILL_NAME / "references"

DETAIL_FILES = (
    "estilo-01-monolith.md",
    "estilo-02-lumen.md",
    "estilo-03-quantum.md",
    "estilo-04-foundry.md",
    "estilo-05-kinetic.md",
    "estilo-06-helix.md",
    "estilo-07-vitalis.md",
    "estilo-08-agent-smith.md",
    "estilo-09-lionclaw-editorial.md",
    "estilo-10-lionclaw-grid.md",
)


def test_all_10_detail_files_exist():
    missing = [f for f in DETAIL_FILES if not (REF_DIR / f).is_file()]
    assert not missing, f"arquivos de detalhe ausentes: {missing}"


def test_index_lists_every_detail_file_as_support_file():
    """O índice (estilos-do-marcos.md) precisa apontar para cada um dos 10 arquivos de detalhe —
    é o mecanismo de progressive disclosure (carrega o índice pequeno, depois só o detalhe do
    estilo escolhido)."""
    index_text = (REF_DIR / "estilos-do-marcos.md").read_text(encoding="utf-8")
    missing = [f for f in DETAIL_FILES if f not in index_text]
    assert not missing, f"índice não referencia: {missing}"


def test_detail_files_have_real_implementation_content():
    """Cada arquivo de detalhe precisa ter token block de cor real (hex), fonte real e pelo menos
    um bloco de código (css/js) — não pode ser um resumo vago tipo o antigo estilos-do-marcos.md."""
    for fname in DETAIL_FILES:
        text = (REF_DIR / fname).read_text(encoding="utf-8")
        assert "```" in text, f"{fname} sem bloco de código"
        assert text.count("#") > 5, f"{fname} sem hex reais suficientes"
        assert len(text) > 2000, f"{fname} parece raso demais para ser implementation-grade"


def test_tecnicas_transversais_exists_and_documents_3d_posture_dichotomy():
    path = REF_DIR / "tecnicas-transversais.md"
    assert path.is_file(), "tecnicas-transversais.md ausente"
    text = path.read_text(encoding="utf-8")
    # a lição de postura 3D: protagonista/interativo vs ambiente/background
    assert "protagonista" in text.lower()
    assert "ambiente" in text.lower() or "background" in text.lower()
    assert "pointer-events" in text
    # outras técnicas transversais citadas na tarefa
    assert "prefers-reduced-motion" in text
    assert "IntersectionObserver" in text
    assert "r128" in text  # convenção Three.js


def test_skill_md_explains_index_then_detail_flow():
    skill_text = (ROOT / SKILL_NAME / "SKILL.md").read_text(encoding="utf-8")
    assert "references/estilos-do-marcos.md" in skill_text
    assert "estilo-NN" in skill_text or "estilo-NN-nome.md" in skill_text
    assert "tecnicas-transversais.md" in skill_text
    assert "${OKAMI_SKILL_DIR}" in skill_text


def test_frontend_design_skill_still_parses_with_new_reference_files():
    bs = {s.name: s for s in load_builtin_skills()}
    assert SKILL_NAME in bs, "skill frontend-design parou de carregar após adicionar referências"


def test_frontend_design_dir_scans_clean_with_all_new_files():
    report = scan_path(ROOT / SKILL_NAME)
    assert not report.blocked, [str(f) for f in report.sorted()]


def test_every_new_reference_file_scans_clean_individually():
    for fname in DETAIL_FILES + ("tecnicas-transversais.md", "estilos-do-marcos.md"):
        report = scan_path(REF_DIR / fname)
        assert not report.blocked, f"{fname} bloqueado no scan: {[str(f) for f in report.sorted()]}"
