"""Identidade e gosto: persona-init/evolve/log/rollback · taste."""
from __future__ import annotations

import typer
from rich.table import Table
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _build_approver, _write_persona_stubs, _persona_ws,
)


@app.command("persona-init")
def persona_init(
    name: str = typer.Option("Okami", "--name", help="Nome do agente."),
    workspace: str = typer.Option("workspaces/default", "--workspace", "-w"),
) -> None:
    """Cria stubs de identidade (SOUL/VOICE/PERSONA) no workspace, se não existirem."""
    created = _write_persona_stubs(Path(workspace), name)
    console.print(f"[green]✓ criados:[/green] {', '.join(created)}" if created
                  else "[dim]identidade já existe (nada criado)[/dim]")
    console.print("[dim]SOUL/VOICE/PERSONA evoluem pelo learning loop (§6/§8); edite à vontade.[/dim]")


@app.command("persona-evolve")
def persona_evolve(
    feedback: str = typer.Argument(..., help="Feedback que molda a identidade (ex.: 'seja mais conciso')."),
    agent: str = typer.Option(None, "-a", "--agent", help="Agente (usa o workspace dele)."),
    workspace: str = typer.Option("workspaces/default", "-w", "--workspace"),
    llm: bool = typer.Option(False, "--llm", help="Refina o bullet via LLM (constrained)."),
    soul: bool = typer.Option(False, "--soul", help="PERMITE editar o SOUL (protegido; pedido explícito)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-aprova (senão pergunta — go/no-go)."),
) -> None:
    """Evolui VOICE/PERSONA a partir de um feedback (go/no-go + changelog + rollback). §8."""
    from okami.learning import persona

    ws = _persona_ws(agent, workspace)
    cfg = _load()
    edit = (persona.propose_llm(cfg, feedback) if llm else persona.propose(feedback))
    # VOICE/PERSONA evoluem AUTO (sem perguntar); SOUL é protegido → exige --soul + go/no-go.
    if soul:
        edit.target = "soul"
        ok = persona.apply_evolution(ws, edit, approve=_build_approver(cfg, yolo=yes), allow_soul=True)
    else:
        ok = persona.apply_evolution(ws, edit, approve=None)
    if ok:
        console.print(f"[green]✓ evoluiu {edit.target.upper()}:[/green] {edit.text}")
        console.print(f"[dim]rollback: okami persona-rollback 1 -w {ws}[/dim]")
    else:
        console.print("[yellow]não aplicado[/yellow] (SOUL exige --soul + aprovação).")


@app.command("persona-log")
def persona_log(
    agent: str = typer.Option(None, "-a", "--agent"),
    workspace: str = typer.Option("workspaces/default", "-w", "--workspace"),
) -> None:
    """Mostra o changelog de evolução da identidade (§8)."""
    from okami.learning import persona

    items = persona.history(_persona_ws(agent, workspace))
    if not items:
        console.print("[dim]nenhuma evolução registrada.[/dim]")
        return
    table = Table(title="Evolução da persona")
    table.add_column("#", style="dim")
    table.add_column("alvo", style="bold")
    table.add_column("texto")
    table.add_column("quando", style="dim")
    for i, it in enumerate(items, 1):
        table.add_row(str(i), it.get("target", "?"), it.get("text", ""), it.get("ts", ""))
    console.print(table)


@app.command("persona-rollback")
def persona_rollback(
    n: int = typer.Argument(1, help="Quantas evoluções reverter (da mais recente)."),
    agent: str = typer.Option(None, "-a", "--agent"),
    workspace: str = typer.Option("workspaces/default", "-w", "--workspace"),
) -> None:
    """Reverte as últimas N evoluções (arquivo + changelog). §8."""
    from okami.learning import persona

    removed = persona.rollback(_persona_ws(agent, workspace), n)
    if not removed:
        console.print("[dim]nada para reverter.[/dim]")
        return
    for r in removed:
        console.print(f"[yellow]revertido[/yellow] {r.get('target')}: {r.get('text')}")


taste_app = typer.Typer(invoke_without_command=True,
                        help="Taste model de design (§9): aprende seu gosto (aprovado→atrai, rejeitado→repele).")
app.add_typer(taste_app, name="taste")


@taste_app.callback(invoke_without_command=True)
def taste_main(ctx: typer.Context) -> None:
    """`okami taste` SEM subcomando → mostra o perfil de gosto atual."""
    if ctx.invoked_subcommand is None:
        taste_show(agent=None, workspace="workspaces/default")


def _taste_feedback(verdict: str, descriptor: str, tags: str | None, agent: str | None, workspace: str):
    from okami.learning import taste

    ws = _persona_ws(agent, workspace)
    tlist = [t.strip() for t in (tags or "").split(",") if t.strip()]
    prof = taste.record_feedback(ws, verdict, descriptor, tlist)
    n = {"approved": "👍", "rejected": "👎", "want_different": "🔄"}.get(taste._VERDICTS.get(verdict, verdict), "•")
    console.print(f"{n} anotado · atratores={len(prof.attractors)} repulsores={len(prof.repulsors)}")
    console.print(f"[dim]{prof.steer()}[/dim]")


@taste_app.command("like")
def taste_like(descriptor: str = typer.Argument(..., help="O que você gostou (ex.: 'shadcn, muted, airy')."),
               tags: str = typer.Option(None, "--tags", help="Tags separadas por vírgula."),
               agent: str = typer.Option(None, "-a", "--agent"),
               workspace: str = typer.Option("workspaces/default", "-w", "--workspace")) -> None:
    """Aprovou um design → vira ATRATOR (estilo a perseguir)."""
    _taste_feedback("approved", descriptor, tags, agent, workspace)


@taste_app.command("dislike")
def taste_dislike(descriptor: str = typer.Argument(..., help="O que não gostou (ex.: 'bootstrap, neon')."),
                  tags: str = typer.Option(None, "--tags"),
                  agent: str = typer.Option(None, "-a", "--agent"),
                  workspace: str = typer.Option("workspaces/default", "-w", "--workspace")) -> None:
    """Rejeitou um design → vira REPULSOR (estilo a evitar)."""
    _taste_feedback("rejected", descriptor, tags, agent, workspace)


@taste_app.command("different")
def taste_different(descriptor: str = typer.Argument(..., help="Design atual que você quer DIFERENTE."),
                    tags: str = typer.Option(None, "--tags"),
                    agent: str = typer.Option(None, "-a", "--agent"),
                    workspace: str = typer.Option("workspaces/default", "-w", "--workspace")) -> None:
    """'Quero diferente' → repulsão LEVE do atual (explora longe dele, perto do que já agradou)."""
    _taste_feedback("want_different", descriptor, tags, agent, workspace)


@taste_app.command("show")
def taste_show(agent: str = typer.Option(None, "-a", "--agent"),
               workspace: str = typer.Option("workspaces/default", "-w", "--workspace")) -> None:
    """Mostra o taste profile (atratores/repulsores) + o steering atual."""
    from okami.learning import taste

    prof = taste.TasteProfile.load(_persona_ws(agent, workspace))
    table = Table(title="Taste profile")
    table.add_column("sinal", style="bold")
    table.add_column("peso", style="dim")
    table.add_column("tags / descritor")
    for it in prof.attractors:
        table.add_row("[green]atrai[/green]", f"{it.weight:.2f}", ", ".join(it.tags) or it.descriptor)
    for it in prof.repulsors:
        table.add_row("[red]repele[/red]", f"{it.weight:.2f}", ", ".join(it.tags) or it.descriptor)
    console.print(table if (prof.attractors or prof.repulsors) else "[dim]sem feedback ainda.[/dim]")
    console.print(f"\n[bold]steering:[/bold]\n{prof.steer()}")


@taste_app.command("steer")
def taste_steer(agent: str = typer.Option(None, "-a", "--agent"),
                workspace: str = typer.Option("workspaces/default", "-w", "--workspace")) -> None:
    """Imprime o bloco de steering que é injetado nos prompts de UI."""
    from okami.learning import taste

    console.print(taste.TasteProfile.load(_persona_ws(agent, workspace)).steer())


