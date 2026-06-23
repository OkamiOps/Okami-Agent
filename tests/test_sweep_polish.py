"""Sweep Hermes — polish de tools (#28 strip base64 no web_extract, #24 teto de char no read_file sem range)."""
from __future__ import annotations

from okami.core.tools import ReadFile, ToolContext
from okami.integrations.web import web_extract


# ---------------------------------------------------------------- #28 base64 fora do contexto
def test_web_extract_strips_base64_image():
    page = "Antes <img src='data:image/png;base64,AAAABBBBCCCCDDDD=='> Depois"
    out = web_extract("https://example.com", max_chars=99999, fetch=lambda u: page)
    assert "base64" not in out.lower() or "removida" in out.lower()
    assert "AAAABBBBCCCC" not in out and "Antes" in out and "Depois" in out


# ---------------------------------------------------------------- #24 teto no read sem range
def test_read_huge_no_range_demands_pagination(tmp_path):
    (tmp_path / "big.txt").write_text("linha\n" * 30000, encoding="utf-8")   # ~180K chars
    r = ReadFile().run({"path": "big.txt"}, ToolContext(workspace=tmp_path))
    assert r.ok is False and ("offset" in r.output or "pagine" in r.output.lower())


def test_read_huge_with_range_still_works(tmp_path):
    (tmp_path / "big.txt").write_text("linha\n" * 30000, encoding="utf-8")
    r = ReadFile().run({"path": "big.txt", "offset": 0, "limit": 5}, ToolContext(workspace=tmp_path))
    assert r.ok                                                   # range explícito = o modelo optou → ok
