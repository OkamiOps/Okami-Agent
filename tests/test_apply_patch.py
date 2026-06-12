"""apply_patch — modo PATCH multi-arquivo (pesquisa #5 item 20, V4A do Hermes/OpenAI).

Um envelope só faz Update/Add/Delete/Move de N arquivos, com hunks de contexto e matching
FUZZY (tolera divergência de whitespace — o edit_file exige match literal). Invariantes:
- atômico ENTRE arquivos: qualquer hunk inválido → NENHUM arquivo é tocado;
- grounding: Update exige o arquivo LIDO (igual edit_file); Add recusa existente;
- Delete é reversível (lixeira), caminho sensível bloqueado, jail de workspace.
"""
from __future__ import annotations

import pytest

from okami.core.tools.base import ToolContext
from okami.core.tools.patch import ApplyPatch, PatchError, parse_patch


def _ctx(tmp_path, read=()):
    c = ToolContext(workspace=tmp_path)
    c.read_files.update(read)
    return c


def _patch(*lines):
    return "*** Begin Patch\n" + "\n".join(lines) + "\n*** End Patch"


# ------------------------------------------------------------------ parser
def test_parse_multi_op():
    ops = parse_patch(_patch(
        "*** Update File: a.py",
        "@@ def foo",
        " ctx",
        "-velho",
        "+novo",
        "*** Add File: b.txt",
        "+linha 1",
        "*** Delete File: c.txt",
    ))
    assert [(o.kind, o.path) for o in ops] == [("update", "a.py"), ("add", "b.txt"), ("delete", "c.txt")]


def test_parse_move_to():
    ops = parse_patch(_patch("*** Update File: a.py", "*** Move to: b/a2.py", " x", "-1", "+2"))
    assert ops[0].move_to == "b/a2.py"


def test_parse_missing_envelope_teaches():
    with pytest.raises(PatchError) as e:
        parse_patch("*** Update File: a.py\n-x\n+y")
    assert "Begin Patch" in str(e.value)


# ------------------------------------------------------------------ aplicação
def test_update_exact_context(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    velho()\n    fim()\n", encoding="utf-8")
    res = ApplyPatch().run({"patch": _patch(
        "*** Update File: a.py", "@@ def foo", "-    velho()", "+    novo()")},
        _ctx(tmp_path, read=["a.py"]))
    assert res.ok, res.output
    assert "novo()" in (tmp_path / "a.py").read_text(encoding="utf-8")
    assert "velho()" not in (tmp_path / "a.py").read_text(encoding="utf-8")


def test_update_fuzzy_whitespace(tmp_path):
    # arquivo tem espaços sobrando no fim das linhas; o patch vem limpo → fuzzy casa mesmo assim
    (tmp_path / "a.py").write_text("inicio()  \n    velho()   \nfim()\n", encoding="utf-8")
    res = ApplyPatch().run({"patch": _patch(
        "*** Update File: a.py", " inicio()", "-    velho()", "+    novo()")},
        _ctx(tmp_path, read=["a.py"]))
    assert res.ok, res.output
    assert "novo()" in (tmp_path / "a.py").read_text(encoding="utf-8")


def test_add_and_delete_and_move(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path / ".home")  # lixeira do teste
    (tmp_path / "morto.txt").write_text("x", encoding="utf-8")
    (tmp_path / "velho.py").write_text("a()\n", encoding="utf-8")
    res = ApplyPatch().run({"patch": _patch(
        "*** Add File: novo.txt",
        "+conteúdo",
        "+linha 2",
        "*** Delete File: morto.txt",
        "*** Update File: velho.py",
        "*** Move to: novo_nome.py",
        "-a()",
        "+b()",
    )}, _ctx(tmp_path, read=["velho.py"]))
    assert res.ok, res.output
    assert (tmp_path / "novo.txt").read_text(encoding="utf-8") == "conteúdo\nlinha 2\n"
    assert not (tmp_path / "morto.txt").exists()              # foi pra lixeira (reversível)
    assert not (tmp_path / "velho.py").exists()
    assert "b()" in (tmp_path / "novo_nome.py").read_text(encoding="utf-8")


def test_atomic_across_files(tmp_path):
    # 2º op tem hunk que NÃO casa → o 1º arquivo NÃO pode ter sido tocado
    (tmp_path / "a.txt").write_text("um\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("dois\n", encoding="utf-8")
    res = ApplyPatch().run({"patch": _patch(
        "*** Update File: a.txt", "-um", "+UM",
        "*** Update File: b.txt", "-NAO-EXISTE", "+x")},
        _ctx(tmp_path, read=["a.txt", "b.txt"]))
    assert not res.ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "um\n"   # intocado
    assert "não encontrado" in res.output or "não casa" in res.output


def test_update_requires_grounding(tmp_path):
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    res = ApplyPatch().run({"patch": _patch("*** Update File: a.txt", "-x", "+y")}, _ctx(tmp_path))
    assert not res.ok and "read_file" in res.output


def test_add_refuses_existing(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    res = ApplyPatch().run({"patch": _patch("*** Add File: a.txt", "+y")}, _ctx(tmp_path))
    assert not res.ok and "existe" in res.output


def test_sensitive_path_blocked(tmp_path):
    res = ApplyPatch().run({"patch": _patch("*** Add File: .env", "+SECRET=1")}, _ctx(tmp_path))
    assert not res.ok and "sensível" in res.output


# ------------------------------------------------------------------ integração registry/aprovação
def test_registered_in_default_registry():
    from okami.core.tools import default_registry
    assert "apply_patch" in default_registry()


def test_identity_file_in_patch_is_sensitive():
    from okami.core.approval import classify
    patch = _patch("*** Update File: SOUL.md", "-a", "+b")
    s = classify("apply_patch", {"patch": patch})
    assert s is not None and s.risk == "high"
