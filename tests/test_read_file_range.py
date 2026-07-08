"""read_file com offset/limit + wrapper <persisted-output> (paridade Hermes tool_result_storage).

Saída de tool grande era truncada com um '[… completo em X …]' solto. Agora vira tag estruturada e o
modelo recupera o resto DE VERDADE com read_file(path, offset, limit) — antes read_file lia tudo (ou
estourava o cap), sem como paginar uma saída de 1MB salva em disco."""

from __future__ import annotations

from okami.core.harness.persisted import persisted_output_wrapper
from okami.core.tools.base import ToolContext
from okami.core.tools.files import ReadFile


def _ctx(tmp_path):
    return ToolContext(workspace=tmp_path, open_fs=False)


def _write(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return name


# ----------------------------------------------------------------- read_file offset/limit
def test_read_offset_skips_lines(tmp_path):
    _write(tmp_path, "f.txt", [f"linha {i}" for i in range(10)])
    r = ReadFile().run({"path": "f.txt", "offset": 5}, _ctx(tmp_path))
    assert r.ok and r.output.startswith("linha 5") and "linha 4" not in r.output


def test_read_limit_caps_lines(tmp_path):
    _write(tmp_path, "f.txt", [f"linha {i}" for i in range(100)])
    r = ReadFile().run({"path": "f.txt", "offset": 0, "limit": 3}, _ctx(tmp_path))
    body = r.output.split("\n\n[")[0]                      # janela, antes da nota de restantes
    assert body.splitlines() == ["linha 0", "linha 1", "linha 2"]


def test_read_offset_and_limit_window(tmp_path):
    _write(tmp_path, "f.txt", [f"L{i}" for i in range(20)])
    r = ReadFile().run({"path": "f.txt", "offset": 8, "limit": 2}, _ctx(tmp_path))
    body = r.output.split("\n\n[")[0]
    assert body.splitlines() == ["L8", "L9"]


def test_read_offset_past_eof_is_clear(tmp_path):
    _write(tmp_path, "f.txt", ["só uma linha"])
    r = ReadFile().run({"path": "f.txt", "offset": 50}, _ctx(tmp_path))
    assert r.ok and ("além do fim" in r.output.lower() or "1 linha" in r.output.lower())


def test_read_no_offset_reads_whole_file(tmp_path):
    _write(tmp_path, "f.txt", ["a", "b", "c"])
    r = ReadFile().run({"path": "f.txt"}, _ctx(tmp_path))
    assert r.output.splitlines() == ["a", "b", "c"]       # back-compat: sem offset/limit = arquivo inteiro


def test_read_truncation_note_reports_more(tmp_path):
    _write(tmp_path, "f.txt", [f"x{i}" for i in range(100)])
    r = ReadFile().run({"path": "f.txt", "limit": 10}, _ctx(tmp_path))
    assert "offset" in r.output.lower() and ("90" in r.output or "mais" in r.output.lower())


# ----------------------------------------------------------------- FIX 3: line_numbers (opt-in)
def test_read_line_numbers_off_by_default(tmp_path):
    _write(tmp_path, "f.txt", ["a", "b", "c"])
    r = ReadFile().run({"path": "f.txt"}, _ctx(tmp_path))
    assert r.output.splitlines() == ["a", "b", "c"]        # sem prefixo — back-compat intacto


def test_read_line_numbers_whole_file(tmp_path):
    _write(tmp_path, "f.txt", ["a", "b", "c"])
    r = ReadFile().run({"path": "f.txt", "line_numbers": True}, _ctx(tmp_path))
    assert r.output.splitlines() == ["1|a", "2|b", "3|c"]


def test_read_line_numbers_with_offset_window(tmp_path):
    _write(tmp_path, "f.txt", [f"L{i}" for i in range(20)])
    r = ReadFile().run({"path": "f.txt", "offset": 8, "limit": 2, "line_numbers": True}, _ctx(tmp_path))
    body = r.output.split("\n\n[")[0]
    assert body.splitlines() == ["9|L8", "10|L9"]           # numeração 1-based da linha REAL do arquivo


# ----------------------------------------------------------------- wrapper <persisted-output>
def test_wrapper_has_tag_path_and_preview():
    w = persisted_output_wrapper(".okami/tool_outputs/step_3.txt", total_chars=120000,
                                 preview="primeiras linhas aqui")
    assert "<persisted-output>" in w and "</persisted-output>" in w
    assert "step_3.txt" in w and "read_file" in w and "offset" in w
    assert "primeiras linhas aqui" in w
    assert "120000" in w or "120" in w                     # menciona o tamanho total
