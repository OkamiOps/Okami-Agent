"""Lint-on-write DELTA (pesquisa #6 item 6, versão 80/20 da Hermes LSP).

Após escrever/editar, valida o arquivo e devolve só o erro NOVO introduzido ("quebrei algo?").
Motor stdlib (py compile / json / toml / yaml) — determinístico, sem linter externo. Editar um
arquivo JÁ quebrado não nagueia (delta: só erro que o 'before' não tinha).
"""
from __future__ import annotations

from okami.core.code_lint import lint_delta


def test_new_python_syntax_error_flagged():
    msg = lint_delta("a.py", "", "def foo(:\n    pass\n")
    assert msg and "a.py" in msg and ("sintax" in msg.lower() or "syntax" in msg.lower() or "linha" in msg.lower())


def test_valid_python_no_flag():
    assert lint_delta("a.py", "", "def foo():\n    return 1\n") == ""


def test_editing_already_broken_does_not_nag():
    before = "def x(:\n  pass\n"            # já quebrado antes
    after = "def x(:\n  pass\n  y = 2\n"    # continua quebrado (mesmo erro)
    assert lint_delta("a.py", before, after) == ""   # erro não é NOVO → não nagueia


def test_introducing_error_into_clean_file_flagged():
    before = "x = 1\n"
    after = "x = (1\n"                       # parêntese aberto → novo erro
    assert lint_delta("a.py", before, after) != ""


def test_json_invalid_flagged():
    assert lint_delta("d.json", "", '{"a": 1,}') != ""        # vírgula sobrando
    assert lint_delta("d.json", "", '{"a": 1}') == ""


def test_toml_invalid_flagged():
    assert lint_delta("p.toml", "", "a = = 1") != ""
    assert lint_delta("p.toml", "", "a = 1") == ""


def test_unknown_extension_ignored():
    assert lint_delta("notes.md", "", "qualquer coisa {[(") == ""   # md não é validado


def test_fixing_a_broken_file_is_clean():
    before = "x = (1\n"                       # quebrado
    after = "x = 1\n"                         # consertou
    assert lint_delta("a.py", before, after) == ""


# ------------------------------------------------------------------ integração no write_file
def test_write_file_appends_lint_warning(tmp_path):
    from okami.core.tools import ToolContext
    from okami.core.tools.files import WriteFile
    ctx = ToolContext(workspace=tmp_path)
    res = WriteFile().run({"path": "bug.py", "content": "def f(:\n  pass\n"}, ctx)
    assert res.ok and res.effect                       # escreveu (lint não bloqueia)
    assert "lint" in res.output.lower() or "sintax" in res.output.lower() or "syntax" in res.output.lower()


def test_write_clean_file_no_warning(tmp_path):
    from okami.core.tools import ToolContext
    from okami.core.tools.files import WriteFile
    ctx = ToolContext(workspace=tmp_path)
    res = WriteFile().run({"path": "ok.py", "content": "x = 1\n"}, ctx)
    assert res.ok and "lint" not in res.output.lower()
