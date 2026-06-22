"""Tool generate_pdf — capacidade que FALTAVA (o agente travava em "gere um pdf" porque não tinha tool,
conversor nem lib). Agora markdown/texto → PDF via fpdf2 (lazy-install, pura-Python)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_generate_pdf_creates_valid_pdf(tmp_path):
    pytest.importorskip("fpdf")          # lazy-dep; no CI sem fpdf2 → pula (a tool instala em runtime)
    pytest.importorskip("markdown")
    from okami.core.tools.pdf import GeneratePdf
    ctx = SimpleNamespace(workspace=tmp_path)
    res = GeneratePdf().run(
        {"content": "# Como funciono\n\nSou o **Okami**.\n- item ç ã é\n", "title": "Relatório",
         "path": "doc.pdf"}, ctx)
    assert res.ok is True and 'MEDIA:"' in res.output           # devolve MEDIA: → gateway anexa
    pdf = tmp_path / "doc.pdf"
    assert pdf.exists() and pdf.read_bytes()[:5] == b"%PDF-"    # é um PDF de VERDADE


def test_generate_pdf_adds_extension(tmp_path):
    pytest.importorskip("fpdf")
    from okami.core.tools.pdf import GeneratePdf
    res = GeneratePdf().run({"content": "oi", "path": "semext"}, SimpleNamespace(workspace=tmp_path))
    assert res.ok and (tmp_path / "semext.pdf").exists()        # força .pdf


def test_generate_pdf_rejects_empty_content(tmp_path):
    from okami.core.tools.pdf import GeneratePdf
    res = GeneratePdf().run({"content": "  "}, SimpleNamespace(workspace=tmp_path))
    assert res.ok is False and "content" in res.output         # validação limpa, não crash


def test_generate_pdf_registered_and_has_spec():
    from okami.core.tools.registry import default_registry
    from okami.core.tool_registry import TOOL_REGISTRY
    assert "generate_pdf" in default_registry()                 # disponível pro modelo
    assert any(s.name == "generate_pdf" for s in TOOL_REGISTRY)  # anti-drift: tem metadata


def test_generate_pdf_from_html_fast_native(tmp_path):
    """HTML estilizado → PDF via xhtml2pdf (instantâneo, sem Chromium) — pro dono não esperar 15min."""
    pytest.importorskip("xhtml2pdf")
    from okami.core.tools.pdf import GeneratePdf
    html = "<html><head><style>h1{color:red}</style></head><body><h1>Oi ção</h1><p>texto</p></body></html>"
    res = GeneratePdf().run({"html": html, "path": "rel.pdf"}, SimpleNamespace(workspace=tmp_path))
    assert res.ok and 'MEDIA:"' in res.output
    pdf = tmp_path / "rel.pdf"
    assert pdf.exists() and pdf.read_bytes()[:5] == b"%PDF-"


def test_generate_pdf_from_html_file(tmp_path):
    """html_path: lê o HTML de um arquivo do workspace (template grande não precisa ir no arg)."""
    pytest.importorskip("xhtml2pdf")
    from okami.core.tools.pdf import GeneratePdf
    (tmp_path / "tpl.html").write_text("<html><body><h1>Template</h1></body></html>")
    res = GeneratePdf().run({"html_path": "tpl.html", "path": "out.pdf"}, SimpleNamespace(workspace=tmp_path))
    assert res.ok and (tmp_path / "out.pdf").read_bytes()[:5] == b"%PDF-"
