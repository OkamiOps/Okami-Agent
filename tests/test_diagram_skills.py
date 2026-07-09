"""Cobertura das skills nativas `diagramas` e `p5js-arte` (porta de
hermes-agent/skills/creative/{excalidraw,architecture-diagram,p5js}).

Ambas são skills de apoio visual/frontend do dono: `diagramas` gera diagrama Excalidraw JSON
(estilo à mão) ou arquitetura SVG dark-theme em HTML; `p5js-arte` gera sketch de arte
generativa/interativa em p5.js. Nenhuma das duas embute script Python — Excalidraw é JSON puro
escrito na hora, arquitetura/p5.js são templates HTML/SVG string-based. Os scripts originais do
Hermes que dependiam de pacote pesado (`cryptography` pro upload do Excalidraw) ou de toolchain
externa (Node/Puppeteer/ffmpeg pro export headless do p5.js) foram DELIBERADAMENTE deixados de
fora — está documentado no corpo de cada SKILL.md.

Este teste cobre: (a) SKILL.md parseia com frontmatter válido, (b) catálogo carrega as duas
skills, (c) scan de segurança não bloqueia nenhum arquivo do diretório da skill, (d) os templates
HTML portados existem e têm conteúdo mínimo esperado, (e) as referências Excalidraw existem.
"""
from __future__ import annotations

from okami.builtin import builtin_skills_root
from okami.skills import catalog, load_builtin_skills
from okami.skills.skill_security import scan_path

ROOT = builtin_skills_root()

DIAGRAMAS_DIR = ROOT / "diagramas"
P5JS_DIR = ROOT / "p5js-arte"


def test_diagramas_and_p5js_dirs_exist():
    assert DIAGRAMAS_DIR.is_dir(), "okami/builtin/skills/diagramas não existe"
    assert P5JS_DIR.is_dir(), "okami/builtin/skills/p5js-arte não existe"
    assert (DIAGRAMAS_DIR / "SKILL.md").is_file()
    assert (P5JS_DIR / "SKILL.md").is_file()


def test_both_skills_load_and_appear_in_catalog():
    bs = load_builtin_skills()
    names = {sk.name for sk in bs}
    assert "diagramas" in names, "skill diagramas não carregou"
    assert "p5js-arte" in names, "skill p5js-arte não carregou"

    cat = catalog(bs)
    assert "diagramas" in cat
    assert "p5js-arte" in cat


def test_both_skills_have_frontmatter_required_fields():
    bs = {sk.name: sk for sk in load_builtin_skills()}
    for name in ("diagramas", "p5js-arte"):
        sk = bs[name]
        assert sk.name and sk.description, f"{name}: name/description ausente no frontmatter"
        assert sk.triggers, f"{name}: sem triggers no frontmatter"
        assert sk.body.strip(), f"{name}: corpo do SKILL.md vazio"


def test_diagramas_skill_scans_clean():
    report = scan_path(DIAGRAMAS_DIR)
    assert not report.blocked, [str(f) for f in report.sorted()]


def test_p5js_skill_scans_clean():
    report = scan_path(P5JS_DIR)
    assert not report.blocked, [str(f) for f in report.sorted()]


def test_diagramas_has_excalidraw_and_architecture_content():
    body = (DIAGRAMAS_DIR / "SKILL.md").read_text(encoding="utf-8")
    # cobre os dois formatos que a skill promete (merge excalidraw + architecture-diagram)
    assert "excalidraw" in body.lower()
    assert "boundElements" in body and "containerId" in body  # binding correto, não "label"
    assert "NÃO use" in body and '"label"' in body  # aviso explícito contra a propriedade fantasma
    assert "architecture.html" in body  # aponta pro template


def test_diagramas_references_and_template_present():
    refs = DIAGRAMAS_DIR / "references"
    tpls = DIAGRAMAS_DIR / "templates"
    assert (refs / "excalidraw-colors.md").is_file()
    assert (refs / "excalidraw-dark-mode.md").is_file()
    assert (refs / "excalidraw-examples.md").is_file()
    arch = tpls / "architecture.html"
    assert arch.is_file()
    html = arch.read_text(encoding="utf-8")
    assert "<svg" in html and "</svg>" in html
    assert "<!DOCTYPE html>" in html


def test_diagramas_skill_has_no_scripts_dir():
    # Nem excalidraw nem architecture-diagram precisam de script Python nesta porta — Excalidraw é
    # JSON puro escrito na hora, arquitetura é HTML/SVG. O script de upload do Hermes (dependência
    # pesada `cryptography`) foi deliberadamente deixado de fora — documentado no SKILL.md.
    assert not (DIAGRAMAS_DIR / "scripts").exists()
    body = (DIAGRAMAS_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "cryptography" in body  # explica por que o upload.py não foi portado


def test_p5js_arte_template_present_and_wellformed():
    tpl = P5JS_DIR / "templates" / "viewer.html"
    assert tpl.is_file()
    html = tpl.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "p5.min.js" in html or "p5.js" in html  # carrega p5 via CDN
    assert "function setup()" in html and "function draw()" in html


def test_p5js_arte_documents_missing_headless_pipeline():
    # setup.sh/render.sh/export-frames.js do Hermes original dependem de Node+Puppeteer+ffmpeg —
    # dependências pesadas fora do escopo desta porta (stdlib/CDN puro). Isso precisa estar
    # documentado no SKILL.md, e nenhum desses scripts deve ter sido copiado.
    assert not (P5JS_DIR / "scripts").exists()
    body = (P5JS_DIR / "SKILL.md").read_text(encoding="utf-8")
    lower = body.lower()
    assert "puppeteer" in lower and "ffmpeg" in lower
    assert "fora do escopo" in lower or "não inclui" in lower


def test_p5js_arte_mentions_seed_determinism_and_export_shortcuts():
    body = (P5JS_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "randomSeed" in body and "noiseSeed" in body
    assert "saveCanvas" in body  # export PNG via atalho de teclado, sem pipeline externo


def test_no_builtin_skill_body_recommends_puppeteer_for_pdf_regression():
    # guarda-corda leve: garante que nossas duas skills novas não colidem com a regra existente
    # (test_builtin_skills_quality.py) que proíbe recomendar puppeteer/chromium perto de "pdf".
    for skill_dir in (DIAGRAMAS_DIR, P5JS_DIR):
        body = (skill_dir / "SKILL.md").read_text(encoding="utf-8").lower()
        if "pdf" not in body:
            continue
        for kw in ("puppeteer", "playwright", "chromium"):
            if kw in body:
                idx = body.index(kw)
                window = body[max(0, idx - 160): idx + 60]
                assert "pdf" not in window
