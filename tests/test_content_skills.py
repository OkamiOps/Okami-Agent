"""Skills nativas documentos-ocr (extração de texto de PDF/imagem) e youtube-resumo (transcrição +
resumo de vídeo do YouTube): SKILL.md parseia com frontmatter, scanner de segurança fica limpo, e os
scripts rodam de verdade quando a dependência/rede está disponível — skipados (não falham) quando
ausente, igual ao padrão do resto da suíte (ex.: test_pdf_edit_skill com pypdf/fpdf2)."""
from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent / "okami" / "builtin" / "skills"

OCR_DIR = ROOT / "documentos-ocr"
OCR_SCRIPT = OCR_DIR / "scripts" / "extract_text.py"

YT_DIR = ROOT / "youtube-resumo"
YT_SCRIPT = YT_DIR / "scripts" / "fetch_transcript.py"

HAS_PYMUPDF = importlib.util.find_spec("pymupdf") is not None


def _online() -> bool:
    """Melhor esforço: tenta abrir um socket até o YouTube. Sem rede -> testes de rede são pulados."""
    try:
        socket.create_connection(("www.youtube.com", 443), timeout=3).close()
        return True
    except OSError:
        return False


ONLINE = _online()


# ─────────────────────────────────────────────────────────────── frontmatter / parse / scanner

@pytest.mark.parametrize("skill_dir,skill_name", [(OCR_DIR, "documentos-ocr"), (YT_DIR, "youtube-resumo")])
def test_skill_md_existe_e_tem_frontmatter(skill_dir, skill_name):
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---")
    assert f"name: {skill_name}" in text
    assert "description:" in text
    assert "triggers:" in text


@pytest.mark.parametrize("skill_dir", [OCR_DIR, YT_DIR])
def test_skill_carrega_via_parse_skill(skill_dir):
    from okami.skills import parse_skill

    sk = parse_skill(skill_dir / "SKILL.md")
    assert sk.name and sk.description
    assert sk.triggers
    assert sk.body


def test_skills_registradas_no_catalogo_builtin():
    """Confirma que as duas pastas novas estão no lugar certo (mesmo nível de editar-pdf/stocks)."""
    assert (ROOT / "editar-pdf" / "SKILL.md").is_file()   # sanity: raiz certa
    assert (OCR_DIR / "SKILL.md").is_file()
    assert (YT_DIR / "SKILL.md").is_file()


def test_skills_aparecem_no_load_builtin_skills():
    from okami.skills import load_builtin_skills

    names = {sk.name for sk in load_builtin_skills()}
    assert "documentos-ocr" in names
    assert "youtube-resumo" in names


@pytest.mark.parametrize("script", [OCR_SCRIPT, YT_SCRIPT])
def test_script_existe_sem_shebang(script):
    text = script.read_text(encoding="utf-8")
    assert not text.startswith("#!")   # scanner de skill penaliza shebang embutido


@pytest.mark.parametrize("skill_dir", [OCR_DIR, YT_DIR])
def test_scanner_de_seguranca_fica_limpo(skill_dir):
    from okami.skills.skill_security import scan_path

    report = scan_path(skill_dir)
    assert not report.blocked, [str(f) for f in report.sorted()]


# ─────────────────────────────────────────────────────────────── documentos-ocr: smoke run

def _run(script: Path, *args: str) -> dict:
    out = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, timeout=30)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_extract_text_sem_pymupdf_degrada_limpo(monkeypatch):
    """Sem pymupdf instalado, o script deve devolver ok:false com instrução — nunca traceback cru."""
    if HAS_PYMUPDF:
        pytest.skip("pymupdf instalado — comportamento de ausência coberto só quando de fato falta")
    # o script tenta lazy_deps.ensure('pdf.pymupdf') (auto-instala sob demanda); p/ testar a DEGRADAÇÃO
    # de verdade, desliga a auto-instalação — aí ele cai no import direto que falha e devolve ok:false.
    monkeypatch.setenv("OKAMI_DISABLE_LAZY_INSTALLS", "1")
    result = _run(OCR_SCRIPT, "arquivo_inexistente.pdf")
    assert result["ok"] is False
    assert "pymupdf" in result["error"].lower()


@pytest.mark.skipif(not HAS_PYMUPDF, reason="pymupdf ausente")
def test_extract_text_pdf_de_verdade(tmp_path):
    pymupdf = __import__("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "ola mundo okami")
    pdf_path = tmp_path / "doc.pdf"
    doc.save(str(pdf_path))

    result = _run(OCR_SCRIPT, str(pdf_path))
    assert result["ok"] is True
    assert result["total_pages"] == 1
    assert "ola mundo okami" in result["pages"][0]["text"]

    meta = _run(OCR_SCRIPT, str(pdf_path), "--metadata")
    assert meta["ok"] is True
    assert meta["pages"] == 1


def test_extract_text_arquivo_inexistente_reporta_erro():
    if not HAS_PYMUPDF:
        pytest.skip("pymupdf ausente — já coberto por test_extract_text_sem_pymupdf_degrada_limpo")
    result = _run(OCR_SCRIPT, "definitivamente_nao_existe.pdf")
    assert result["ok"] is False


# ─────────────────────────────────────────────────────────────── youtube-resumo: smoke run

def test_extract_video_id_formatos():
    sys.path.insert(0, str(YT_DIR / "scripts"))
    try:
        import fetch_transcript as ft

        assert ft.extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert ft.extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert ft.extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert ft.extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    finally:
        sys.path.remove(str(YT_DIR / "scripts"))
        sys.modules.pop("fetch_transcript", None)


def test_format_timestamp():
    sys.path.insert(0, str(YT_DIR / "scripts"))
    try:
        import fetch_transcript as ft

        assert ft.format_timestamp(5) == "0:05"
        assert ft.format_timestamp(65) == "1:05"
        assert ft.format_timestamp(3665) == "1:01:05"
    finally:
        sys.path.remove(str(YT_DIR / "scripts"))
        sys.modules.pop("fetch_transcript", None)


def test_fetch_transcript_video_invalido_reporta_erro_sem_travar():
    """Sem rede, ou com um ID inválido, o script deve terminar com ok:false — nunca travar/estourar."""
    if not ONLINE:
        pytest.skip("sem rede — smoke de rede pulado")
    result = _run(YT_SCRIPT, "id-invalido-000")
    assert result["ok"] is False
    assert "error" in result


@pytest.mark.skipif(not ONLINE, reason="sem rede")
def test_fetch_transcript_video_real_com_legenda():
    """Vídeo curto e estável do canal oficial do YouTube (com legenda). Best-effort: se o YouTube
    mudar layout/remover a legenda, este teste específico pode ficar frágil — por isso segue
    isolado dos testes estruturais acima, que não dependem de rede."""
    out = _run(YT_SCRIPT, "jNQXAC9IVRw")  # "Me at the zoo" — 1º vídeo do YouTube
    if out.get("ok") is False:
        pytest.skip(f"legenda indisponível neste ambiente: {out.get('error')}")
    assert out["ok"] is True
    assert out["video_id"] == "jNQXAC9IVRw"
    assert out["full_text"]
