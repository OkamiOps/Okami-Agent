"""Memória do workspace: memory add/search/list."""
from __future__ import annotations

import typer
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load,
)


mem_app = typer.Typer(invoke_without_command=True, help="Inspecionar/editar a memória de um workspace.")
app.add_typer(mem_app, name="memory")


@mem_app.callback(invoke_without_command=True)
def memory_main(ctx: typer.Context) -> None:
    """`okami memory` SEM subcomando → lista a memória (não pede argumento; estilo hermes/openclaw)."""
    if ctx.invoked_subcommand is None:
        memory_list(workspace="workspaces/default")


def _open_mem(workspace: str):
    from okami.memory import make_embedder, open_memory

    cfg = _load()
    return open_memory(Path(workspace), backend=cfg.memory.get("backend", "sqlite-fts5"),
                       embedder=make_embedder(cfg.memory.get("embedder")), config=cfg.memory)


@mem_app.command("add")
def memory_add(
    text: str = typer.Argument(..., help="Fato a guardar."),
    workspace: str = typer.Option("workspaces/default", "--workspace", "-w"),
) -> None:
    """Guarda um fato na memória do workspace."""
    from okami.memory import MemoryItem

    m = _open_mem(workspace)
    m.write(MemoryItem(text=text, kind="fact", source="cli"))
    m.close()
    console.print("[green]✓ lembrado[/green]")


@mem_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Busca (full-text)."),
    workspace: str = typer.Option("workspaces/default", "--workspace", "-w"),
) -> None:
    """Busca na memória (híbrida)."""
    m = _open_mem(workspace)
    items = m.recall(query, 10)
    m.close()
    if not items:
        console.print("[dim]nada encontrado[/dim]")
        return
    for i in items:
        console.print(f"- [dim][{i.kind}][/dim] {i.text[:160]}")


@mem_app.command("list")
def memory_list(
    workspace: str = typer.Option("workspaces/default", "--workspace", "-w"),
) -> None:
    """Lista os itens recentes da memória."""
    m = _open_mem(workspace)
    items = m.recent(20)
    total = m.count()
    fts = m.fts
    m.close()
    console.print(f"[dim]{total} itens · FTS5={'on' if fts else 'LIKE (sem FTS5)'}[/dim]")
    for i in items:
        console.print(f"- [dim][{i.kind}][/dim] {i.text[:160]}")


