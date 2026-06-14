"""Guarda anti-stale nas tools de escrita (pesquisa #7 item 7).

`file_state.record_read` grava o mtime no momento da leitura; antes de SOBRESCREVER, a tool
de escrita pergunta `check_stale` e BLOQUEIA (effect=False) se o arquivo mudou no disco depois
da leitura — força uma releitura em vez de apagar mudanças que o agente nunca viu.

Cobertura: write/edit/patch bloqueados quando o arquivo mudou após a leitura; ok quando
inalterado; prelearned (sem mtime gravado) não dá falso-positivo; arquivo novo passa.
"""
from __future__ import annotations

import os

from okami.core.tools import ToolContext
from okami.core.tools.files import EditFile, ReadFile, WriteFile
from okami.core.tools.patch import ApplyPatch


def _bump_mtime(p) -> None:
    """Empurra o mtime do arquivo p/ frente (simula edição externa DEPOIS da leitura do agente)."""
    novo = p.stat().st_mtime + 100
    os.utime(p, (novo, novo))


# ------------------------------------------------------------------ ReadFile grava o baseline
def test_read_file_registra_mtime(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    ctx = ToolContext(workspace=tmp_path)
    res = ReadFile().run({"path": "a.py"}, ctx)
    assert res.ok
    assert "a.py" in ctx.read_files
    assert ctx.read_mtimes.get("a.py") == f.stat().st_mtime


# ------------------------------------------------------------------ WriteFile
def test_write_bloqueia_quando_arquivo_mudou_apos_leitura(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    ctx = ToolContext(workspace=tmp_path)
    ReadFile().run({"path": "a.py"}, ctx)
    _bump_mtime(f)                                   # alguém editou depois que o agente leu
    res = WriteFile().run({"path": "a.py", "content": "x = 2\n"}, ctx)
    assert res.ok is False
    assert res.effect is False                       # nada foi escrito
    assert "mudou" in res.output.lower() or "releia" in res.output.lower() or "leia de novo" in res.output.lower()
    assert f.read_text() == "x = 1\n"                # conteúdo no disco intacto


def test_write_ok_quando_inalterado(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    ctx = ToolContext(workspace=tmp_path)
    ReadFile().run({"path": "a.py"}, ctx)
    res = WriteFile().run({"path": "a.py", "content": "x = 2\n"}, ctx)
    assert res.ok and res.effect
    assert f.read_text() == "x = 2\n"


def test_write_arquivo_novo_ok(tmp_path):
    """Arquivo que não existe → sem baseline, sem grounding exigido → escreve normal."""
    ctx = ToolContext(workspace=tmp_path)
    res = WriteFile().run({"path": "novo.py", "content": "x = 1\n"}, ctx)
    assert res.ok and res.effect
    assert (tmp_path / "novo.py").read_text() == "x = 1\n"


def test_write_prelearned_sem_falso_positivo(tmp_path):
    """Arquivo 'prelearned' do harness entra em read_files SEM mtime gravado → check_stale fail-opens.
    A escrita não pode ser bloqueada por falta de baseline (senão prelearned vira impossível de editar)."""
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    ctx = ToolContext(workspace=tmp_path)
    ctx.read_files.add("a.py")                       # prelearned: rel presente, mtime AUSENTE
    res = WriteFile().run({"path": "a.py", "content": "x = 9\n"}, ctx)
    assert res.ok and res.effect                     # sem baseline → não bloqueia
    assert f.read_text() == "x = 9\n"


# ------------------------------------------------------------------ EditFile
def test_edit_bloqueia_quando_arquivo_mudou(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    ctx = ToolContext(workspace=tmp_path)
    ReadFile().run({"path": "a.py"}, ctx)
    _bump_mtime(f)
    res = EditFile().run({"path": "a.py", "old": "x = 1", "new": "x = 2"}, ctx)
    assert res.ok is False
    assert res.effect is False
    assert f.read_text() == "x = 1\n"


def test_edit_ok_quando_inalterado(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    ctx = ToolContext(workspace=tmp_path)
    ReadFile().run({"path": "a.py"}, ctx)
    res = EditFile().run({"path": "a.py", "old": "x = 1", "new": "x = 2"}, ctx)
    assert res.ok and res.effect
    assert f.read_text() == "x = 2\n"


def test_edit_prelearned_sem_falso_positivo(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    ctx = ToolContext(workspace=tmp_path)
    ctx.read_files.add("a.py")                       # prelearned, sem mtime
    res = EditFile().run({"path": "a.py", "old": "x = 1", "new": "x = 5"}, ctx)
    assert res.ok and res.effect
    assert f.read_text() == "x = 5\n"


# ------------------------------------------------------------------ ApplyPatch
def _patch_update(rel: str, old: str, new: str) -> str:
    return ("*** Begin Patch\n"
            f"*** Update File: {rel}\n"
            f"-{old}\n"
            f"+{new}\n"
            "*** End Patch\n")


def test_patch_bloqueia_quando_arquivo_mudou(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    ctx = ToolContext(workspace=tmp_path)
    ReadFile().run({"path": "a.py"}, ctx)
    _bump_mtime(f)
    res = ApplyPatch().run({"patch": _patch_update("a.py", "x = 1", "x = 2")}, ctx)
    assert res.ok is False
    assert res.effect is False
    assert f.read_text() == "x = 1\n"                # nada aplicado


def test_patch_ok_quando_inalterado(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    ctx = ToolContext(workspace=tmp_path)
    ReadFile().run({"path": "a.py"}, ctx)
    res = ApplyPatch().run({"patch": _patch_update("a.py", "x = 1", "x = 2")}, ctx)
    assert res.ok and res.effect
    assert f.read_text() == "x = 2\n"


def test_patch_prelearned_sem_falso_positivo(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    ctx = ToolContext(workspace=tmp_path)
    ctx.read_files.add("a.py")                       # prelearned, sem mtime
    res = ApplyPatch().run({"patch": _patch_update("a.py", "x = 1", "x = 7")}, ctx)
    assert res.ok and res.effect
    assert f.read_text() == "x = 7\n"


def test_patch_add_arquivo_novo_ok(tmp_path):
    """Add File de arquivo novo → sem baseline e sem grounding → cria normal (anti-stale não atrapalha)."""
    ctx = ToolContext(workspace=tmp_path)
    patch = ("*** Begin Patch\n"
             "*** Add File: novo.py\n"
             "+x = 1\n"
             "*** End Patch\n")
    res = ApplyPatch().run({"patch": patch}, ctx)
    assert res.ok and res.effect
    assert (tmp_path / "novo.py").read_text() == "x = 1\n"
