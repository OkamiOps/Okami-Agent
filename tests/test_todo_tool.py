"""Testes do item 9 (metade tool): TodoWrite + render_pending.

A CHECKLIST operacional do modelo sobrevive à compactação — `todo_write` substitui a
lista inteira em `ctx.todos`; `render_pending` formata só os itens pendentes/em andamento
pra reinjetar no contexto depois de compactar.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from okami.core.tools.base import ToolContext
from okami.core.tools.todo import TodoWrite, render_pending


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace=tmp_path)


# ---------- forma / atributos da tool ----------

def test_tool_atributos():
    t = TodoWrite()
    assert t.name == "todo_write"
    assert t.required == ("todos",)
    assert "todos" in t.args_schema
    assert t.terminal is False


# ---------- run(): substitui a lista inteira ----------

def test_substitui_lista_inteira(ctx):
    ctx.todos[:] = [{"id": "velho", "content": "antigo", "status": "completed"}]
    res = TodoWrite().run({"todos": [
        {"id": "1", "content": "passo um", "status": "pending"},
        {"id": "2", "content": "passo dois", "status": "in_progress"},
    ]}, ctx)
    assert res.ok is True
    assert res.effect is False
    # a lista virou a nova (o antigo sumiu) — substituição, não append
    assert [t["content"] for t in ctx.todos] == ["passo um", "passo dois"]
    assert "velho" not in [t["id"] for t in ctx.todos]


def test_conta_abertos_na_mensagem(ctx):
    res = TodoWrite().run({"todos": [
        {"content": "a", "status": "pending"},
        {"content": "b", "status": "in_progress"},
        {"content": "c", "status": "completed"},
    ]}, ctx)
    assert res.ok is True
    # 2 itens != completed → "2 aberto(s)"
    assert "2 aberto" in res.output


# ---------- run(): coação de status e geração de id ----------

def test_status_invalido_coagido_para_pending(ctx):
    res = TodoWrite().run({"todos": [
        {"content": "x", "status": "blah"},
        {"content": "y"},  # sem status
    ]}, ctx)
    assert res.ok is True
    assert all(t["status"] == "pending" for t in ctx.todos)


def test_gera_id_quando_falta(ctx):
    res = TodoWrite().run({"todos": [{"content": "sem id"}]}, ctx)
    assert res.ok is True
    assert ctx.todos[0].get("id")  # id gerado, não-vazio


def test_status_validos_preservados(ctx):
    TodoWrite().run({"todos": [
        {"content": "a", "status": "pending"},
        {"content": "b", "status": "in_progress"},
        {"content": "c", "status": "completed"},
    ]}, ctx)
    assert [t["status"] for t in ctx.todos] == ["pending", "in_progress", "completed"]


# ---------- run(): formas inválidas → ok False ----------

def test_todos_nao_e_lista(ctx):
    res = TodoWrite().run({"todos": "não é lista"}, ctx)
    assert res.ok is False
    assert res.effect is False
    # falha não muta a lista
    assert ctx.todos == []


def test_item_sem_content(ctx):
    res = TodoWrite().run({"todos": [{"id": "1", "status": "pending"}]}, ctx)
    assert res.ok is False
    assert ctx.todos == []


def test_item_nao_e_dict(ctx):
    res = TodoWrite().run({"todos": ["string solta"]}, ctx)
    assert res.ok is False
    assert ctx.todos == []


def test_lista_vazia_e_valida(ctx):
    # zerar a checklist é válido (limpa tudo, 0 abertos)
    ctx.todos[:] = [{"id": "1", "content": "x", "status": "pending"}]
    res = TodoWrite().run({"todos": []}, ctx)
    assert res.ok is True
    assert ctx.todos == []
    assert "0 aberto" in res.output


# ---------- render_pending ----------

def test_render_vazio_sem_pendentes():
    assert render_pending([]) == ""
    assert render_pending([{"content": "feito", "status": "completed"}]) == ""


def test_render_inclui_pending_e_in_progress():
    out = render_pending([
        {"content": "fazer A", "status": "pending"},
        {"content": "fazendo B", "status": "in_progress"},
        {"content": "feito C", "status": "completed"},
    ])
    assert out != ""
    assert "CHECKLIST OPERACIONAL ATIVA" in out
    assert "fazer A" in out
    assert "fazendo B" in out
    # completed NÃO entra no bloco de pendentes
    assert "feito C" not in out


def test_render_mostra_status_no_bloco():
    out = render_pending([{"content": "tarefa", "status": "in_progress"}])
    assert "[in_progress] tarefa" in out
    assert "NAO recomece" in out
