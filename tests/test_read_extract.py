"""Tier 1 (#9): read_file extrai texto de .docx/.xlsx/.ipynb via stdlib (zipfile+ElementTree), ZERO
dep nova. Hoje o agente trata Office como binário e fica cego ao conteúdo que o dono manda."""
from __future__ import annotations

import json
import zipfile

_DOCX_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _make_docx(p, paras):
    body = "".join(f'<w:p><w:r><w:t>{t}</w:t></w:r></w:p>' for t in paras)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="{_DOCX_NS}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", xml)


def _make_xlsx(p):
    shared = (f'<?xml version="1.0"?><sst xmlns="{_XLSX_NS}">'
              '<si><t>Nome</t></si><si><t>Idade</t></si></sst>')
    sheet = (f'<?xml version="1.0"?><worksheet xmlns="{_XLSX_NS}"><sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
             '<row r="2"><c r="A2"><v>42</v></c></row></sheetData></worksheet>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("xl/sharedStrings.xml", shared)
        z.writestr("xl/worksheets/sheet1.xml", sheet)


def test_extract_ipynb(tmp_path):
    from okami.core.read_extract import extract_text
    nb = {"cells": [{"cell_type": "markdown", "source": ["# Título\n", "texto"]},
                    {"cell_type": "code", "source": ["print('oi')"]}], "nbformat": 4}
    p = tmp_path / "n.ipynb"
    p.write_text(json.dumps(nb), encoding="utf-8")
    out = extract_text(p)
    assert "# Título" in out and "print('oi')" in out


def test_extract_docx(tmp_path):
    from okami.core.read_extract import extract_text
    p = tmp_path / "d.docx"
    _make_docx(p, ["Olá mundo", "linha 2"])
    out = extract_text(p)
    assert "Olá mundo" in out and "linha 2" in out


def test_extract_xlsx(tmp_path):
    from okami.core.read_extract import extract_text
    p = tmp_path / "s.xlsx"
    _make_xlsx(p)
    out = extract_text(p)
    assert "Nome" in out and "Idade" in out and "42" in out


def test_is_extractable_and_none_for_plain(tmp_path):
    from okami.core.read_extract import extract_text, is_extractable
    assert is_extractable("a.docx") and is_extractable("X.XLSX") and is_extractable("n.ipynb")
    assert not is_extractable("foo.txt")
    assert extract_text(tmp_path / "foo.txt") is None    # tipo não-extraível → None


def test_corrupt_office_returns_none(tmp_path):
    from okami.core.read_extract import extract_text
    p = tmp_path / "bad.docx"
    p.write_text("não é um zip", encoding="utf-8")
    assert extract_text(p) is None                       # corrompido → None (não crasha)


def test_malformed_ipynb_does_not_crash(tmp_path):
    # achado da review #9: .ipynb com JSON-lista no topo NÃO pode levantar AttributeError (crashava o turno).
    from okami.core.read_extract import extract_text
    from okami.core.tools import ReadFile, ToolContext
    p = tmp_path / "weird.ipynb"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert extract_text(p) in ("", None)                 # sem crash
    r = ReadFile().run({"path": "weird.ipynb"}, ToolContext(workspace=tmp_path))
    assert r.ok or "extrair" in r.output.lower()         # tool devolve resultado limpo, não exceção


def test_read_file_tool_extracts_docx(tmp_path):
    from okami.core.tools import ReadFile, ToolContext
    p = tmp_path / "carta.docx"
    _make_docx(p, ["conteúdo do docx"])
    r = ReadFile().run({"path": "carta.docx"}, ToolContext(workspace=tmp_path))
    assert r.ok and "conteúdo do docx" in r.output
