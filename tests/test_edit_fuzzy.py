"""Paridade Hermes: edit_file tolera divergência de WHITESPACE/indentação no `old` (o erro nº1 do modelo
é não reproduzir espaço/indent exato), e o grounding (ler antes de editar) vira AVISO, não BLOQUEIO — já que
o `old` precisa casar conteúdo real (o match JÁ é o grounding). Era a causa nº1 de 'edita arquivo e falha'."""
from __future__ import annotations

from okami.core.tools import EditFile, ToolContext


def test_edit_tolerates_whitespace_indent_mismatch(tmp_path):
    (tmp_path / "code.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path, read_files={"code.py"})
    # old com indentação ERRADA (2 espaços em vez de 4) — Hermes casa fuzzy e edita; Okami antes recusava
    res = EditFile().run(
        {"path": "code.py", "old": "def f():\n  return 1", "new": "def f():\n    return 2"}, ctx)
    assert res.ok, res.output
    assert "return 2" in (tmp_path / "code.py").read_text(encoding="utf-8")


def test_edit_tolerates_trailing_whitespace(tmp_path):
    (tmp_path / "a.py").write_text("alvo = 1   \n", encoding="utf-8")   # espaço sobrando no fim no arquivo
    ctx = ToolContext(workspace=tmp_path, read_files={"a.py"})
    res = EditFile().run({"path": "a.py", "old": "alvo = 1", "new": "alvo = 2"}, ctx)   # old limpo
    assert res.ok, res.output
    assert "alvo = 2" in (tmp_path / "a.py").read_text(encoding="utf-8")


def test_edit_grounding_is_warning_not_block(tmp_path):
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path)                 # NÃO leu o arquivo (read_files vazio)
    res = EditFile().run({"path": "code.py", "old": "x = 1", "new": "x = 2"}, ctx)
    assert res.ok, res.output                             # não bloqueia (Hermes só avisa); old casa = grounding
    assert "x = 2" in (tmp_path / "code.py").read_text(encoding="utf-8")


def test_edit_genuinely_wrong_old_still_fails_with_hint(tmp_path):
    (tmp_path / "code.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path, read_files={"code.py"})
    # conteúdo REALMENTE diferente (não é só whitespace) → não casa nem fuzzy → erro que ensina
    res = EditFile().run({"path": "code.py", "old": "def zzz():\n    return 99", "new": "x"}, ctx)
    assert res.ok is False
