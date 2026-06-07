"""Memória do workspace: add/search/list + CRUD/auditoria (forget/archive/explain/export)."""
from __future__ import annotations

import typer
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load,
)


mem_app = typer.Typer(invoke_without_command=True, help="Inspecionar/editar a memória de um workspace.")
app.add_typer(mem_app, name="memory")

_WS = typer.Option("workspaces/default", "--workspace", "-w")
_GLOBAL = typer.Option(False, "--global", "-g", help="Opera na memória GLOBAL (~/.okami), não a do projeto.")


@mem_app.callback(invoke_without_command=True)
def memory_main(ctx: typer.Context) -> None:
    """`okami memory` SEM subcomando → lista a memória (não pede argumento; estilo hermes/openclaw)."""
    if ctx.invoked_subcommand is None:
        memory_list(workspace="workspaces/default")


def _open_mem(workspace: str):
    """Memória COMPLETA (com layer global se ligado) — para ler/buscar/listar."""
    from okami.memory import make_embedder, open_memory

    cfg = _load()
    return open_memory(Path(workspace), backend=cfg.memory.get("backend", "sqlite-fts5"),
                       embedder=make_embedder(cfg.memory.get("embedder")), config=cfg.memory)


def _crud_store(workspace: str, global_: bool):
    """Store CONCRETO (projeto OU casa) — CRUD por id é local a um store."""
    from okami.home import okami_home
    from okami.memory import make_embedder, open_store

    cfg = _load()
    base = okami_home() if global_ else Path(workspace) / ".okami"
    return open_store(base, backend=cfg.memory.get("backend", "sqlite-fts5"),
                      embedder=make_embedder(cfg.memory.get("embedder")), config=cfg.memory)


def _parse_id(raw: str, global_flag: bool) -> tuple[int, bool]:
    """'g1' / 'global:1' → casa · 'project:1' / '1' → projeto. Desambigua o #id que a `list` mostra."""
    s = str(raw).strip().lower().lstrip("#")
    for pre in ("global:", "casa:"):
        if s.startswith(pre):
            return int(s[len(pre):]), True
    for pre in ("project:", "projeto:", "workspace:", "ws:"):
        if s.startswith(pre):
            return int(s[len(pre):]), False
    if s.startswith("g") and s[1:].isdigit():
        return int(s[1:]), True
    return int(s), global_flag


@mem_app.command("add")
def memory_add(
    text: str = typer.Argument(..., help="Fato a guardar."),
    workspace: str = _WS,
    global_: bool = _GLOBAL,
    scope: str = typer.Option("", "--scope", help="Escopo explícito (global|workspace|user:<id>|…)."),
) -> None:
    """Guarda um fato (a política classifica a categoria). `--global` = preferência que vale em qualquer projeto."""
    from okami.memory.policy import prepare

    item = prepare(text, source="cli", force=True)   # usuário explícito → sempre persiste, mas classificado
    if item is None:
        console.print("[yellow]nada a guardar (texto vazio).[/yellow]")
        raise typer.Exit(1)
    is_global = global_ or scope == "global"
    item.scope = "global" if is_global else (scope or "workspace")
    store = _crud_store(workspace, is_global)
    store.write(item)
    store.close()
    where = "global (~/.okami)" if is_global else "projeto"
    console.print(f"[green]✓ lembrado[/green] [dim]({item.kind} · escopo={item.scope} · {where})[/dim]")


@mem_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Busca (full-text)."),
    workspace: str = _WS,
) -> None:
    """Busca na memória (híbrida; inclui a global se ligada)."""
    m = _open_mem(workspace)
    items = m.recall(query, 10)
    m.close()
    if not items:
        console.print("[dim]nada encontrado[/dim]")
        return
    from okami.memory.citation import cite
    for i in items:
        idp = f"[dim]#{i.id}[/dim] " if i.id is not None else ""
        console.print(f"- {idp}{i.text[:160]}  [dim]{cite(i)}[/dim]")


@mem_app.command("list")
def memory_list(
    workspace: str = _WS,
) -> None:
    """Lista os itens recentes da memória (com #id para forget/explain)."""
    m = _open_mem(workspace)
    items = m.recent(20)
    total = m.count()
    fts = getattr(m, "fts", None)                    # P2: LayeredMemory não tem .fts → não quebra
    health = m.health()                              # P2: saúde por camada (Honcho pode estar morto)
    m.close()
    fts_label = "" if fts is None else f" · FTS5={'on' if fts else 'LIKE'}"
    console.print(f"[dim]{total} itens{fts_label}[/dim]")
    for h in (health.get("layers") or [health]):     # avisa camada degradada (ex.: honcho offline)
        if not h.get("ok", True):
            console.print(f"[yellow]⚠ camada {h.get('backend')}: {h.get('failures')} falha(s)"
                          + (f' — {h["last_error"][:60]}' if h.get("last_error") else "") + "[/yellow]")
    for i in items:
        gp = "g" if (i.scope or "").startswith("global") else ""    # global #N vs projeto #N → prefixo p/ desambiguar
        idp = f"[dim]{gp}#{i.id}[/dim] " if i.id is not None else ""
        sc = "" if (i.scope or "workspace") == "workspace" else f" [dim]<{i.scope}>[/dim]"
        console.print(f"- {idp}[dim][{i.kind}][/dim] {i.text[:150]}{sc}")


@mem_app.command("forget")
def memory_forget(
    item_id: str = typer.Argument(..., help="#id do item (ver `okami memory list`; use g1/global:1 p/ a casa)."),
    workspace: str = _WS,
    global_: bool = _GLOBAL,
) -> None:
    """Esquece um item — some do retrieval e NÃO volta via recall."""
    n, g = _parse_id(item_id, global_)
    store = _crud_store(workspace, g)
    ok = store.forget_item(n)
    store.close()
    console.print("[green]✓ esquecido[/green]" if ok else f"[red]✗ id #{item_id} não encontrado[/red]")
    if not ok:
        raise typer.Exit(1)


@mem_app.command("prune")
def memory_prune(
    workspace: str = _WS,
    global_: bool = _GLOBAL,
    dry_run: bool = typer.Option(False, "--dry-run", help="Só lista o que removeria (não apaga)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Remove sem confirmar."),
) -> None:
    """Poda memória auto-aprendida de baixo valor (post-mortems de tarefa ancorados na frase do pedido:
    'COMO: para …' e 'ANTI-PADRÃO … terminou …'). Fatos/preferências/decisões ficam intactos."""
    from okami import learning

    store = _crud_store(workspace, global_)
    victims = [i for i in store.recent(100000) if learning.is_reflection_noise(i)]
    if not victims:
        store.close()
        console.print("[green]✓ nada a podar — sem memória auto-aprendida de baixo valor.[/green]")
        return
    console.print(f"[yellow]{len(victims)} item(ns) de memória auto-aprendida de baixo valor:[/yellow]")
    for i in victims[:30]:
        console.print(f"  • [dim][{i.kind}][/dim] {(i.text or '')[:88]}")
    if len(victims) > 30:
        console.print(f"  [dim]… +{len(victims) - 30}[/dim]")
    if dry_run:
        store.close()
        console.print("[dim]--dry-run: nada removido.[/dim]")
        return
    if not yes:
        from okami import menu
        if not menu.confirm(f"Remover {len(victims)} item(ns)?", default=False):
            store.close()
            console.print("[dim]cancelado.[/dim]")
            return
    removed = sum(1 for i in victims if i.id is not None and store.forget_item(i.id))
    store.close()
    console.print(f"[green]✓ podados {removed} item(ns).[/green] "
                  "[dim]reflect agora só aprende de falha real (não de papo/exploração).[/dim]")


@mem_app.command("archive")
def memory_archive(
    item_id: str = typer.Argument(..., help="#id do item (use g1/global:1 p/ a casa)."),
    workspace: str = _WS,
    global_: bool = _GLOBAL,
) -> None:
    """Arquiva um item — some do retrieval, mas marcado 'archived' (intencional)."""
    n, g = _parse_id(item_id, global_)
    store = _crud_store(workspace, g)
    ok = store.archive_item(n)
    store.close()
    console.print("[green]✓ arquivado[/green]" if ok else f"[red]✗ id #{item_id} não encontrado[/red]")
    if not ok:
        raise typer.Exit(1)


@mem_app.command("explain")
def memory_explain(
    item_id: str = typer.Argument(..., help="#id do item (use g1/global:1 p/ a casa)."),
    workspace: str = _WS,
    global_: bool = _GLOBAL,
) -> None:
    """Por que/quando esta memória apareceu: metadados + últimas recuperações (retrieval_logs)."""
    import datetime as _dt

    n, g = _parse_id(item_id, global_)
    store = _crud_store(workspace, g)
    info = store.explain(n)
    store.close()
    if not info:
        console.print(f"[red]✗ id #{item_id} não encontrado[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]#{info['id']}[/bold] [dim][{info['kind']}][/dim] {info['text'][:200]}")
    console.print(f"  escopo=[cyan]{info['scope']}[/cyan] · confiança={info['confidence']} · "
                  f"status={info['status']} · origem={info['source']} · "
                  f"importância={info['importance']:.2f} · usos={info['access_count']}")
    if info.get("supersedes_id"):
        console.print(f"  [dim]substitui #{info['supersedes_id']}[/dim]")
    rets = info.get("retrievals") or []
    if not rets:
        console.print("  [dim]ainda não foi recuperada em nenhuma busca[/dim]")
    else:
        console.print("  [dim]últimas recuperações:[/dim]")
        for r in rets:
            when = _dt.datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M") if r.get("ts") else "?"
            console.print(f"    · {when}  score={r['score']:.2f} rank={r['rank']}  “{(r['query'] or '')[:60]}”")


@mem_app.command("stats")
def memory_stats(
    workspace: str = _WS,
    global_: bool = _GLOBAL,
    json_out: bool = typer.Option(False, "--json", help="Saída JSON (pra script/CI)."),
) -> None:
    """Métricas da memória (#13): composição, compactness, integridade do forget e health score."""
    from okami.memory import metrics

    store = _crud_store(workspace, global_)
    rep = metrics.report(store)
    store.close()
    if json_out:
        import json
        console.print_json(json.dumps(rep, ensure_ascii=False))
        return
    st, obs, integ = rep["stats"], rep["observed"], rep["integrity"]
    score = rep["health_score"]
    color = "green" if score >= 0.8 else "yellow" if score >= 0.6 else "red"
    console.print(f"🧠 [bold]memória[/bold] · {st.get('total_active', 0)} ativos / {st.get('total_all', 0)} total "
                  f"· health [{color}]{score:.2f}[/{color}]")
    console.print(f"  composição: {st.get('by_kind', {})}")
    console.print(f"  escopo: {st.get('by_scope', {})} · confiança: {st.get('by_confidence', {})} "
                  f"· status: {st.get('by_status', {})}")
    console.print(f"  recall: {(st.get('retrievals') or {}).get('count', 0)} buscas · "
                  f"score médio {obs['avg_retrieval_score']} "
                  f"· compactness {obs['context_compactness']} itens/consulta")
    fs = integ["forget_success_rate"]
    fc = "green" if fs >= 1.0 else "red"
    console.print(f"  integridade do forget: [{fc}]{fs:.2f}[/{fc}] "
                  f"({integ['leaked_forgotten']} vazaram de {integ['inactive_total']} inativos) "
                  f"· consolidado {obs['consolidation_rate']}")
    console.print("  [dim]precision/recall/scope: rode o harness com casos rotulados "
                  "(okami.memory.metrics.evaluate)[/dim]")


@mem_app.command("consolidate")
def memory_consolidate(
    workspace: str = _WS,
    global_: bool = _GLOBAL,
) -> None:
    """Consolida (heurístico, sem LLM): expira TTL vencido + funde quase-duplicatas (marca 'superseded')."""
    store = _crud_store(workspace, global_)
    r = store.consolidate()
    store.close()
    console.print(f"[green]✓ consolidado[/green] [dim]({r.get('expired', 0)} expirados · "
                  f"{r.get('merged', 0)} fundidos)[/dim]")


@mem_app.command("export")
def memory_export(
    workspace: str = _WS,
    global_: bool = _GLOBAL,
) -> None:
    """Dump auditável (JSON) de toda a memória — debug/backup/migração."""
    import json

    store = _crud_store(workspace, global_)
    data = store.export()
    store.close()
    console.print_json(json.dumps(data, ensure_ascii=False))
