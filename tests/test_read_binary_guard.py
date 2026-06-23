"""Paridade Hermes (#29): read_file recusa BINÁRIO (extensão conhecida OU NUL nos 1os bytes) com msg clara
— senão um PNG/objeto vira mojibake/lixo no contexto. Imagem aponta o vision_analyze."""
from __future__ import annotations

from okami.core.tools import ReadFile, ToolContext


def test_read_png_redirects_to_vision(tmp_path):
    (tmp_path / "foto.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
    r = ReadFile().run({"path": "foto.png"}, ToolContext(workspace=tmp_path))
    assert r.ok is False and "vision_analyze" in r.output


def test_read_binary_no_ext_detected_by_nul(tmp_path):
    (tmp_path / "blob").write_bytes(b"texto\x00\x00binario")
    r = ReadFile().run({"path": "blob"}, ToolContext(workspace=tmp_path))
    assert r.ok is False and "binári" in r.output.lower()


def test_read_normal_text_still_works(tmp_path):
    (tmp_path / "a.txt").write_text("conteúdo de texto normal", encoding="utf-8")
    r = ReadFile().run({"path": "a.txt"}, ToolContext(workspace=tmp_path))
    assert r.ok and "conteúdo de texto normal" in r.output
