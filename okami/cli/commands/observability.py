"""Observabilidade: rollback (checkpoints) · events (timeline) · replay (trajetória do turno)."""
from __future__ import annotations

import typer

from okami.cli._app import app, console
from okami.cli._shared import _persona_ws


@app.command()
def rollback(
    n: int = typer.Argument(1, help="Quantas escritas de arquivo reverter (da mais recente)."),
    agent: str = typer.Option(None, "-a", "--agent"),
    workspace: str = typer.Option(".", "-w", "--workspace"),
) -> None:
    """Desfaz as últimas N escritas de arquivo (checkpoints — rede de segurança estilo Hermes)."""
    from okami.gateway.checkpoints import Checkpoints

    reverted = Checkpoints(_persona_ws(agent, workspace)).rollback(n)
    if not reverted:
        console.print("[dim]nada para reverter.[/dim]")
        return
    for p in reverted:
        console.print(f"[yellow]revertido[/yellow] {p}")


@app.command()
def events(
    agent: str = typer.Option(None, "-a", "--agent"),
    workspace: str = typer.Option(".", "-w", "--workspace"),
    n: int = typer.Option(40, "-n", help="Quantos eventos finais mostrar."),
) -> None:
    """Timeline da última task (replay/debug) — .okami/events.jsonl."""
    import datetime as _dt

    from okami.observability.events import read_events
    ws = _persona_ws(agent, workspace)
    evs = read_events(ws)
    if not evs:
        console.print(f"[dim]sem eventos em {ws}/.okami/events.jsonl[/dim]")
        return
    for e in evs[-n:]:
        ts = e.get("ts")
        hhmm = _dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if isinstance(ts, (int, float)) else "--:--:--"
        extra = {k: v for k, v in e.items() if k not in ("seq", "ts", "type")}
        brief = "  ".join(f"[dim]{k}=[/dim]{str(v)[:60]}" for k, v in extra.items())
        console.print(f"[dim]{e.get('seq', '?'):>3} {hhmm}[/dim] [bold #ff7527]{e.get('type', '?')}[/bold #ff7527] {brief}")
    calls = [e for e in evs if e.get("type") == "llm_call"]      # resumo de usage por-chamada (P2)
    if calls:
        ti = sum(int(e.get("tokens_in", 0) or 0) for e in calls)
        to = sum(int(e.get("tokens_out", 0) or 0) for e in calls)
        traces = {e.get("trace") for e in evs if e.get("trace")}
        console.print(f"[dim]── {len(calls)} chamada(s) LLM · {ti:,} tok in · {to:,} tok out"
                      f"{f' · {len(traces)} turno(s)' if traces else ''} ──[/dim]")


@app.command()
def replay(
    trace: str = typer.Argument(None, help="trace_id do turno (sem arg = lista os turnos recentes)."),
    agent: str = typer.Option(None, "-a", "--agent"),
    workspace: str = typer.Option(".", "-w", "--workspace"),
    json_out: bool = typer.Option(False, "--json", help="Saída JSON (CI/ferramenta)."),
) -> None:
    """Replay da TRAJETÓRIA de um turno (#12): `okami replay` lista turnos; `okami replay <trace>` detalha."""
    import datetime as _dt

    from okami.observability.trajectory import build_trajectory, list_traces, render_line
    ws = _persona_ws(agent, workspace)
    if not trace:                                     # sem trace → lista os turnos p/ escolher
        traces = list_traces(ws)
        if json_out:
            import json as _json
            console.print_json(_json.dumps({"traces": traces}, ensure_ascii=False))
            return
        from okami.cli import _ui
        console.print()
        console.print(_ui.header("replay", "trajetórias dos turnos recentes"))
        console.print()
        if not traces:
            console.print(_ui.hint(f"sem turnos em {ws}/.okami/events.jsonl"))
            return
        t = _ui.data_table(
            ("trace", {"style": f"bold {_ui.CYAN}", "no_wrap": True}),
            ("quando", {"style": _ui.MUTE, "no_wrap": True}),
            ("passos", {"justify": "right", "no_wrap": True}),
            ("llm", {"justify": "right", "no_wrap": True}),
            ("tokens", {"style": _ui.MUTE, "no_wrap": True}),
            ("desfecho", {"no_wrap": True}),
            ("objetivo", {"style": _ui.SOFT, "overflow": "ellipsis", "no_wrap": True}),
        )
        for s in traces:
            when = (_dt.datetime.fromtimestamp(s["ended_at"]).strftime("%m-%d %H:%M")
                    if s.get("ended_at") else "—")
            t.add_row(s["trace"], when, str(s["steps"]), str(s["llm_calls"]),
                      f"↑{s['tokens_in']} ↓{s['tokens_out']}", s["outcome"], str(s["goal"]))
        console.print(t)
        console.print(_ui.hint("okami replay <trace> — trajetória completa do turno"))
        console.print()
        return
    traj = build_trajectory(ws, trace)
    if json_out:
        import json as _json
        console.print_json(_json.dumps(traj, ensure_ascii=False))
        return
    if not traj["events"]:
        console.print(f"[yellow]trace '{trace}' não encontrado[/yellow] em {ws}/.okami/events.jsonl")
        raise typer.Exit(1)
    from okami.cli import _ui
    s = traj["summary"]
    console.print()
    console.print(_ui.header(f"replay {trace}",
                             f"{s['outcome']} · {s['steps']} passos · {s['llm_calls']} LLM · "
                             f"↑{s['tokens_in']} ↓{s['tokens_out']}"))
    console.print()
    for e in traj["events"]:
        console.print(render_line(e))
    console.print()
