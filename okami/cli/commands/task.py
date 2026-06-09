"""Comando `task` — roda o harness até COMPLETE/BLOCKED/NEEDS_INPUT/FAILED."""
from __future__ import annotations

import typer
from okami.i18n import t as _tr
from okami.core import TaskState
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _build_approver, _parse_exit, _STATE_COLOR,
)


@app.command(help=_tr("cli.task", _default="Run the harness until COMPLETE/BLOCKED/NEEDS_INPUT/FAILED."))
def task(
    goal: str = typer.Argument(None, help=_tr("cli.task.goal", _default="Task goal (if empty, prompts).")),
    provider: str = typer.Option(None, "--provider", "-p"),
    model: str = typer.Option(None, "--model", "-m"),
    workspace: str = typer.Option("workspaces/default", "--workspace", "-w", help=_tr("cli.task.workspace", _default="Working directory.")),
    exit_: list[str] = typer.Option(None, "--exit", "-e", help=_tr("cli.task.exit", _default="Exit criterion (repeatable).")),
    max_steps: int = typer.Option(24, "--max-steps"),
    escalate_to: str = typer.Option(None, "--escalate", help=_tr("cli.task.escalate", _default="Strong provider to cascade to if stuck.")),
    yes: bool = typer.Option(False, "--yes", "-y", "--yolo", help=_tr("cli.task.yes", _default="YOLO: auto-approve everything in the session.")),
    mode: str = typer.Option(None, "--mode", help=_tr("cli.task.mode", _default="Approval: manual | smart | off.")),
    agent: str = typer.Option(None, "--agent", "-a", help=_tr("cli.task.agent", _default="Run as an agent (agents/<id>).")),
) -> None:
    """Roda o harness até COMPLETE/BLOCKED/NEEDS_INPUT/FAILED."""
    if not goal or not goal.strip():            # `okami task` sem objetivo → pergunta (não dá erro seco)
        import sys
        if sys.stdin.isatty():
            goal = (typer.prompt("Qual o objetivo da tarefa?") or "").strip()
        if not goal or not goal.strip():
            console.print('[yellow]informe um objetivo:[/yellow] okami task "criar X / consertar Y"   '
                          "[dim](ou `okami chat` p/ conversar)[/dim]")
            raise typer.Exit(2)
    if agent:
        from okami.agents import effective_config, load_agents
        from okami.config import load_raw
        graw, _ = load_raw()
        specs = load_agents()
        if agent not in specs:
            console.print(f"[red]agente '{agent}' não existe. Crie: okami agent new {agent}[/red]")
            raise typer.Exit(1)
        cfg = effective_config(graw, specs[agent])
        ws = specs[agent].dir
        console.print(f"[dim]agente:[/dim] [bold]{agent}[/bold] [dim](workspace {ws})[/dim]")
    else:
        cfg = _load()
        ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    criteria = []
    for s in (exit_ or []):
        if s == "ui_gate":
            criteria.append({"type": "ui_gate", "contract": cfg.contracts.get("ui", {}), "path": "."})
        else:
            criteria.append(_parse_exit(s))

    def on_event(e: dict) -> None:
        k = e["kind"]
        if k == "start":
            console.print(f"[bold]▶ tarefa:[/bold] {e['goal']}\n[dim]workspace={ws}[/dim]")
        elif k == "step":
            mark = "[green]ok[/green]" if e["ok"] else "[red]erro[/red]"
            console.print(f"  [dim]{e['n']:>2}[/dim] {e['tool']} → {mark}")
        elif k == "violation":
            console.print(f"  [yellow]⟲ rejeitado (sem ação) #{e['n']}[/yellow]")
        elif k == "loop":
            console.print(f"  [yellow]⟲ loop detectado[/yellow] (x{e['repeats']})")
        elif k == "escalate":
            console.print(f"  [magenta]⬆ escalando p/ '{escalate_to}'[/magenta] [dim]({e['why']})[/dim]")
        elif k == "compact":
            console.print(f"  [blue]⊟ auto-compaction[/blue] [dim]({e['promoted']} → memória)[/dim]")
        elif k == "complete_rejected":
            console.print(f"  [yellow]✗ task_complete rejeitado:[/yellow] {', '.join(e['missing'])}")

    approver = _build_approver(cfg, yolo=yes, mode=mode)
    if approver.mode in ("yolo", "off"):
        console.print(f"[dim]aprovação: {approver.mode} (sem prompts)[/dim]")

    from okami.runner import run_task
    try:
        result = run_task(cfg, ws, goal, exit_criteria=criteria, provider=provider, model=model,
                          approve=approver, on_event=on_event, max_steps=max_steps,
                          escalate_to=escalate_to, emit=lambda m: console.print(f"[dim]{m}[/dim]"))
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Erro no harness:[/red] {e}")
        raise typer.Exit(1)

    color = _STATE_COLOR.get(result.state, "white")
    console.print(f"\n[bold {color}]{result.state.value}[/bold {color}] "
                  f"[dim]({len(result.steps)} passos)[/dim]")
    if result.result:
        console.print(result.result)
    if result.reason:
        console.print(f"[dim]{result.reason}[/dim]")
    if result.state != TaskState.COMPLETE:
        raise typer.Exit(2)


