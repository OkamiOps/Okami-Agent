"""Skill editar-pdf: SKILL.md parseia, scanner de segurança fica limpo, e o script edita um PDF
de verdade (metadata/extract/patch/rotate/merge/split). Requer pypdf+fpdf2 instalados — os testes
que precisam deles são SKIPADOS (não FALHAM) quando ausentes, igual ao padrão do resto da suíte
(ex.: test_browser_a11y com Playwright)."""
from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent / "okami" / "builtin" / "skills" / "editar-pdf"
SCRIPT = SKILL_DIR / "scripts" / "edit_pdf.py"

HAS_PYPDF = importlib.util.find_spec("pypdf") is not None
HAS_FPDF = importlib.util.find_spec("fpdf") is not None


def test_skill_md_existe_e_tem_frontmatter():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name: editar-pdf" in text
    assert "triggers:" in text


def test_script_existe_sem_shebang():
    text = SCRIPT.read_text(encoding="utf-8")
    assert not text.startswith("#!")           # scanner de skill penaliza shebang embutido


def test_scanner_de_seguranca_fica_limpo():
    from okami.skills.skill_security import scan_path
    report = scan_path(SKILL_DIR)
    assert not report.blocked, [str(f) for f in report.sorted()]


def test_skill_esta_registrada_no_catalogo_builtin():
    """okami/builtin/skills é a raiz de skills embutidas — confirma que a pasta está no lugar certo
    (mesmo nível de criar-pull-request/stocks/etc), sem exercitar o loader completo (fora de escopo)."""
    root = SKILL_DIR.parent
    assert (root / "editar-pdf" / "SKILL.md").is_file()
    assert (root / "stocks" / "SKILL.md").is_file()   # sanity: raiz certa


def _run(*args) -> dict:
    out = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not (HAS_PYPDF and HAS_FPDF), reason="pypdf/fpdf2 ausentes")
def test_smoke_metadata_extract_patch_rotate_merge_split(tmp_path):
    from fpdf import FPDF

    src = tmp_path / "src.pdf"
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=16)
    pdf.set_xy(40, 40)
    pdf.cell(0, 10, "titulo antigo")
    pdf.output(str(src))

    info = _run("info", str(src))
    assert info["ok"] and info["pages"] == 1

    meta_out = tmp_path / "meta.pdf"
    meta = _run("metadata", str(src), str(meta_out), "--title", "Titulo Novo")
    assert meta["ok"] and meta_out.exists()
    info2 = _run("info", str(meta_out))
    assert info2["metadata"].get("Title") == "Titulo Novo"

    patch_out = tmp_path / "patch.pdf"
    patched = _run("patch", str(src), str(patch_out), "--page", "1",
                   "--rect", "30,730,300,770", "--text", "titulo corrigido", "--font-size", "14")
    assert patched["ok"] and patch_out.exists()
    extracted = _run("extract", str(patch_out), "--page", "1")
    assert "titulo corrigido" in extracted["text"]

    rot_out = tmp_path / "rot.pdf"
    rot = _run("rotate", str(patch_out), str(rot_out), "--page", "1", "--degrees", "90")
    assert rot["ok"] and rot_out.exists()

    merged_out = tmp_path / "merged.pdf"
    merged = _run("merge", str(merged_out), str(src), str(patch_out))
    assert merged["ok"] and merged["pages"] == 2

    split_dir = tmp_path / "split"
    split = _run("split", str(merged_out), str(split_dir))
    assert split["ok"] and len(split["files"]) == 2
    assert all(Path(f).exists() for f in split["files"])


@pytest.mark.skipif(not (HAS_PYPDF and HAS_FPDF), reason="pypdf/fpdf2 ausentes")
def test_pagina_fora_do_intervalo_da_erro_json(tmp_path):
    from fpdf import FPDF
    src = tmp_path / "src.pdf"
    pdf = FPDF()
    pdf.add_page()
    pdf.output(str(src))
    out = subprocess.run([sys.executable, str(SCRIPT), "extract", str(src), "--page", "99"],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode != 0
    payload = json.loads(out.stdout.strip())
    assert payload["ok"] is False
    assert "intervalo" in payload["error"]
