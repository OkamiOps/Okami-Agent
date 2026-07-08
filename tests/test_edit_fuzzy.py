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


# ------------------------------------------------------------ novas estratégias (paridade Hermes 9-chain)

def test_edit_tolerates_escaped_newline_literal(tmp_path):
    """escape_normalized: o modelo manda '\\n' LITERAL (2 chars, artefato de serialização) onde o arquivo
    tem quebra de linha REAL — sem essa estratégia o `old` (1 'linha' só, com backslash-n no meio) não casa
    em NENHUM nível anterior (exato/rstrip/strip/uninorm comparam por linha de verdade)."""
    (tmp_path / "code.py").write_text("def f():\n    x = 1\n    return x\n", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path, read_files={"code.py"})
    old = "x = 1\\n    return x"          # backslash + 'n' LITERAL, não quebra de linha real
    res = EditFile().run({"path": "code.py", "old": old, "new": "x = 1\\n    return x * 2"}, ctx)
    assert res.ok, res.output
    assert "return x * 2" in (tmp_path / "code.py").read_text(encoding="utf-8")


def test_edit_tolerates_curly_quote_drift(tmp_path):
    """unicode_normalized: arquivo tem aspas curvas/travessão 'bonitos' que o modelo reproduz como ASCII
    reto — já existia o nível uninorm em _find_block, mas faltava cobertura de teste dedicada."""
    (tmp_path / "msg.py").write_text('greeting = "It’s a test — ok?"\n', encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path, read_files={"msg.py"})
    res = EditFile().run(
        {"path": "msg.py", "old": 'greeting = "It\'s a test - ok?"', "new": 'greeting = "changed"'}, ctx)
    assert res.ok, res.output
    assert "changed" in (tmp_path / "msg.py").read_text(encoding="utf-8")


def test_edit_block_anchor_tolerates_middle_drift(tmp_path):
    """block_anchor: bloco de 4 linhas onde só o MEIO divergiu de verdade (comentário reformulado + espaço
    dentro dos parênteses) — 1ª/última linha casam exato, meio casa por SIMILARIDADE (threshold 0.50 p/
    candidato único). Nem exato/rstrip/strip/uninorm/escape/trimmed_boundary casam (o meio difere em
    CONTEÚDO, não só whitespace de borda)."""
    (tmp_path / "calc.py").write_text(
        "def calc():\n    # compute value\n    x = compute_value(1, 2, 3)\n    return x\n",
        encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path, read_files={"calc.py"})
    old = "def calc():\n    # compute the value\n    x = compute_value(1,2,3)\n    return x"
    res = EditFile().run({"path": "calc.py", "old": old, "new": "def calc():\n    return 0"}, ctx)
    assert res.ok, res.output
    assert "return 0" in (tmp_path / "calc.py").read_text(encoding="utf-8")


def test_edit_multiline_indentation_drift_already_covered(tmp_path):
    """indentation_flexible já existe via o nível 'strip' de _find_block (rstrip→strip por linha) — confirma
    que segue funcionando p/ um bloco de VÁRIAS linhas com indentação toda errada (não só 1 linha)."""
    (tmp_path / "multi.py").write_text(
        "class C:\n    def m(self):\n        a = 1\n        b = 2\n        return a + b\n", encoding="utf-8")
    ctx = ToolContext(workspace=tmp_path, read_files={"multi.py"})
    old = "def m(self):\n  a = 1\n  b = 2\n  return a + b"     # indent errado (2 espaços) em TODAS as linhas
    res = EditFile().run({"path": "multi.py", "old": old, "new": "def m(self):\n        return 99"}, ctx)
    assert res.ok, res.output
    assert "return 99" in (tmp_path / "multi.py").read_text(encoding="utf-8")
