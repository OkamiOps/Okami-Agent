"""Port de 3 ergonomias de arquivo do Hermes que faltavam em files.py (dono: PORTAR, não remendar):

1. READ did-you-mean: read_file numa path que não existe sugere até 3 nomes PARECIDOS na mesma pasta
   (tools/file_operations.py:1141-1191 _suggest_similar_files).
2. CRLF/BOM preservation: read→edit/write não normaliza silenciosamente um arquivo Windows pra LF nem
   descarta o BOM (tools/file_operations.py:991-1027 / :1368-1389).
3. Per-line truncation: 1 linha minificada/gigante não floda o contexto mesmo com o arquivo inteiro
   dentro do teto geral (tools/file_operations.py:869-893).
"""
from __future__ import annotations

from okami.core.tools.base import ToolContext
from okami.core.tools.files import EditFile, ReadFile, WriteFile


def _ctx(tmp_path, **kw):
    return ToolContext(workspace=tmp_path, **kw)


# ----------------------------------------------------------------- 1) READ did-you-mean
def test_read_missing_file_suggests_sibling(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print(1)\n", encoding="utf-8")
    r = ReadFile().run({"path": "src/mian.py"}, _ctx(tmp_path))
    assert r.ok is False
    assert "main.py" in r.output


def test_read_missing_file_no_siblings_stays_clean(tmp_path):
    r = ReadFile().run({"path": "nope.txt"}, _ctx(tmp_path))
    assert r.ok is False
    assert "nope.txt" in r.output
    assert "não existe" in r.output.lower()


# ----------------------------------------------------------------- 2) CRLF/BOM preservation
def test_new_file_write_stays_lf(tmp_path):
    ctx = _ctx(tmp_path)
    r = WriteFile().run({"path": "new.txt", "content": "a\nb\n"}, ctx)
    assert r.ok
    raw = (tmp_path / "new.txt").read_bytes()
    assert b"\r\n" not in raw


def test_crlf_file_survives_edit_roundtrip(tmp_path):
    p = tmp_path / "win.txt"
    p.write_bytes(b"linha1\r\nlinha2\r\nlinha3\r\n")
    ctx = _ctx(tmp_path)
    read1 = ReadFile().run({"path": "win.txt"}, ctx)
    assert read1.ok
    assert "\r" not in read1.output          # o modelo vê LF puro (universal newlines)
    e = EditFile().run({"path": "win.txt", "old": "linha2", "new": "linhaDOIS"}, ctx)
    assert e.ok, e.output
    raw = p.read_bytes()
    assert b"\r\n" in raw                     # CRLF preservado no disco
    assert raw.count(b"\r\n") == 3
    assert b"linhaDOIS" in raw
    read2 = ReadFile().run({"path": "win.txt"}, ctx)
    assert "linhaDOIS" in read2.output and "\r" not in read2.output


def test_crlf_file_survives_write_roundtrip(tmp_path):
    p = tmp_path / "win2.txt"
    p.write_bytes(b"a\r\nb\r\n")
    ctx = _ctx(tmp_path, read_files={"win2.txt"})
    w = WriteFile().run({"path": "win2.txt", "content": "a\nb\nc\n"}, ctx)
    assert w.ok, w.output
    raw = p.read_bytes()
    assert raw == b"a\r\nb\r\nc\r\n"


def test_bom_file_survives_edit_roundtrip(tmp_path):
    p = tmp_path / "bom.txt"
    p.write_bytes(b"\xef\xbb\xbf" + "primeira\nsegunda\n".encode("utf-8"))
    ctx = _ctx(tmp_path)
    read1 = ReadFile().run({"path": "bom.txt"}, ctx)
    assert read1.ok
    assert not read1.output.startswith("﻿")     # BOM não vaza pro modelo
    e = EditFile().run({"path": "bom.txt", "old": "primeira", "new": "PRIMEIRA"}, ctx)
    assert e.ok, e.output
    raw = p.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")            # BOM preservado
    assert b"PRIMEIRA" in raw


# ----------------------------------------------------------------- 3) per-line truncation
def test_huge_line_gets_truncated_others_intact(tmp_path):
    huge = "x" * 5000
    p = tmp_path / "huge.txt"
    p.write_text(f"antes\n{huge}\ndepois\n", encoding="utf-8")
    r = ReadFile().run({"path": "huge.txt"}, _ctx(tmp_path))
    assert r.ok
    lines = r.output.splitlines()
    assert lines[0] == "antes"
    assert lines[2] == "depois"
    assert len(lines[1]) < 5000
    assert "truncad" in lines[1].lower()
    assert "5000" in lines[1]


def test_short_lines_unaffected_by_truncation(tmp_path):
    p = tmp_path / "small.txt"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    r = ReadFile().run({"path": "small.txt"}, _ctx(tmp_path))
    assert r.output.splitlines() == ["a", "b", "c"]
