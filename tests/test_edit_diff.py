"""Diff curto na saída de sucesso do edit_file / apply_patch (pesquisa #7 item 8).

Quando uma edição passa, o resumo agora carrega o número da 1ª linha mudada (rel:LINHA) e um
diff unified curto (difflib.unified_diff, capado em _DIFF_MAX_LINES) — o agente vê exatamente o
que mudou sem precisar reler o arquivo. Aditivo: o resumo antigo ("editado X (N substituições)")
continua presente.
"""
from __future__ import annotations

from okami.core.tools import ToolContext
from okami.core.tools.files import EditFile, ReadFile


def _ctx_with_file(tmp_path, name, content):
    f = tmp_path / name
    f.write_text(content)
    ctx = ToolContext(workspace=tmp_path)
    ReadFile().run({"path": name}, ctx)              # grounding + baseline anti-stale
    return ctx, f


# ------------------------------------------------------------------ número de linha + marcadores de diff
def test_edit_saida_inclui_numero_de_linha(tmp_path):
    ctx, f = _ctx_with_file(tmp_path, "a.py", "a = 1\nb = 2\nc = 3\n")
    res = EditFile().run({"path": "a.py", "old": "b = 2", "new": "b = 22"}, ctx)
    assert res.ok
    assert "a.py:2" in res.output                    # 1ª (e única) linha mudada = linha 2


def test_edit_saida_inclui_marcadores_de_diff(tmp_path):
    ctx, f = _ctx_with_file(tmp_path, "a.py", "a = 1\nb = 2\nc = 3\n")
    res = EditFile().run({"path": "a.py", "old": "b = 2", "new": "b = 22"}, ctx)
    assert res.ok
    # diff unified: linha removida começa com '-', adicionada com '+'
    assert "-b = 2" in res.output
    assert "+b = 22" in res.output


def test_edit_mantem_resumo_antigo(tmp_path):
    """Aditivo: o resumo existente ('editado … substituição') segue presente além do diff."""
    ctx, f = _ctx_with_file(tmp_path, "a.py", "a = 1\nb = 2\n")
    res = EditFile().run({"path": "a.py", "old": "b = 2", "new": "b = 9"}, ctx)
    assert res.ok
    assert "editado" in res.output.lower()
    assert "substitui" in res.output.lower()


def test_edit_primeira_linha_quando_mudanca_no_meio(tmp_path):
    """A linha reportada é a 1ª que mudou, mesmo com a edição lá pra baixo."""
    src = "\n".join(f"l{i} = {i}" for i in range(1, 11)) + "\n"
    ctx, f = _ctx_with_file(tmp_path, "big.py", src)
    res = EditFile().run({"path": "big.py", "old": "l7 = 7", "new": "l7 = 77"}, ctx)
    assert res.ok
    assert "big.py:7" in res.output


def test_edit_replace_all_reporta_primeira_ocorrencia(tmp_path):
    """replace_all=True: a linha reportada é a da 1ª ocorrência trocada (mais alta no arquivo)."""
    src = "x = 0\ny = 0\nx = 0\n"
    ctx, f = _ctx_with_file(tmp_path, "r.py", src)
    res = EditFile().run({"path": "r.py", "old": "x = 0", "new": "x = 1", "replace_all": True}, ctx)
    assert res.ok
    assert "r.py:1" in res.output                    # 1ª ocorrência mudada está na linha 1
    assert "2 substitui" in res.output.lower()       # resumo conta as duas


def test_edit_multilinha_reporta_primeira_linha_mudada(tmp_path):
    """Bloco multi-linha: a linha reportada é a 1ª que de fato diverge."""
    src = "def f():\n    a = 1\n    b = 2\n    return a + b\n"
    ctx, f = _ctx_with_file(tmp_path, "m.py", src)
    old = "    a = 1\n    b = 2"
    new = "    a = 10\n    b = 20"
    res = EditFile().run({"path": "m.py", "old": old, "new": new}, ctx)
    assert res.ok
    assert "m.py:2" in res.output                    # 1ª linha do bloco trocado = linha 2
    assert "-    a = 1" in res.output or "-a = 1" in res.output


def test_edit_diff_capado(tmp_path):
    """Edição enorme → diff capado em _DIFF_MAX_LINES (não despeja o arquivo inteiro no resumo)."""
    from okami.tui import _DIFF_MAX_LINES
    src = "\n".join(f"linha {i}" for i in range(200)) + "\n"
    ctx, f = _ctx_with_file(tmp_path, "huge.py", src)
    # troca tudo por um bloco igualmente grande mas diferente
    new = "\n".join(f"LINHA {i}" for i in range(200)) + "\n"
    res = EditFile().run({"path": "huge.py", "old": src, "new": new}, ctx)
    assert res.ok
    # o trecho de diff anexado não pode ter centenas de linhas '+'/'-'
    diff_marks = [ln for ln in res.output.splitlines() if ln.lstrip().startswith(("+", "-"))]
    assert len(diff_marks) <= _DIFF_MAX_LINES + 2    # margem p/ a linha "truncado"
