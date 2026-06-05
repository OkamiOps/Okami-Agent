"""Replay/trajetória por TURNO (#12 — debug trajectory).

O event log (`.okami/events.jsonl`) já grava tudo com `trace` (= um turno). Aqui a gente RECONSTRÓI:
agrupa os eventos por trace, resume cada turno (objetivo, nº de passos, chamadas de LLM, tokens,
desfecho) e devolve a sequência ordenada de UM turno p/ replay/debug. É o que alimenta `okami replay`.
"""

from __future__ import annotations

from pathlib import Path

from okami.observability.events import read_events

_OUTCOME = {"complete": "✓ completou", "blocked": "⊘ bloqueou", "need_input": "? pediu input",
            "complete_rejected": "✗ rejeitado (exit criteria)"}


def _trace_key(e: dict) -> str:
    return str(e.get("trace") or "(sem trace)")


def _summarize(events: list[dict]) -> dict:
    """Resumo de UM turno a partir dos seus eventos (já filtrados por trace)."""
    steps = [e for e in events if e.get("type") == "step"]
    llm = [e for e in events if e.get("type") == "llm_call"]
    goal = next((e.get("goal") for e in events if e.get("type") == "start"), "")
    outcome = next((_OUTCOME[e["type"]] for e in reversed(events)
                    if e.get("type") in _OUTCOME), "… (incompleto)")
    tin = sum(int(e.get("tokens_in", 0) or 0) for e in llm)
    tout = sum(int(e.get("tokens_out", 0) or 0) for e in llm)
    ts = [e.get("ts", 0) for e in events if e.get("ts")]
    return {
        "trace": _trace_key(events[0]) if events else "",
        "goal": goal or "",
        "steps": len(steps),
        "llm_calls": len(llm),
        "tokens_in": tin,
        "tokens_out": tout,
        "outcome": outcome,
        "started_at": min(ts) if ts else None,
        "ended_at": max(ts) if ts else None,
    }


def list_traces(workspace: Path, *, name: str = "events", limit: int = 20) -> list[dict]:
    """Resumo dos turnos (mais recentes primeiro) p/ escolher qual dar replay."""
    by: dict[str, list[dict]] = {}
    for e in read_events(workspace, name=name):
        by.setdefault(_trace_key(e), []).append(e)
    summaries = [_summarize(evs) for evs in by.values()]
    summaries.sort(key=lambda s: s.get("ended_at") or 0, reverse=True)
    return summaries[:limit]


def build_trajectory(workspace: Path, trace_id: str, *, name: str = "events") -> dict:
    """Sequência ordenada (por seq) de UM turno + resumo. `events: []` se o trace não existir."""
    evs = [e for e in read_events(workspace, name=name) if _trace_key(e) == trace_id]
    evs.sort(key=lambda e: e.get("seq", 0))
    return {"trace": trace_id, "summary": _summarize(evs) if evs else {}, "events": evs}


def render_line(e: dict) -> str:
    """Uma linha legível por evento (p/ o replay no terminal)."""
    t = e.get("type", "?")
    if t == "start":
        return f"▶ start · {str(e.get('goal', ''))[:80]}"
    if t == "llm_call":
        tok = f"↑{e.get('tokens_in', 0)} ↓{e.get('tokens_out', 0)}"
        cache = f" cache={e.get('cache_read')}" if e.get("cache_read") else ""
        return f"  🧠 llm · {e.get('provider', '')}/{e.get('model', '')} · {tok}{cache} · {e.get('finish_reason', '')}"
    if t == "step":
        mark = "✓" if e.get("ok") else "✗"
        return f"  {mark} step {e.get('n', '?')} · {e.get('tool', '')}"
    if t in ("approval", "approval_request"):
        return f"  ⚠ approval · {e.get('tool', '')} · {e.get('decision', e.get('category', ''))}"
    if t == "failure":
        return f"  ⨯ failure · {e.get('kind', '')} · {str(e.get('detail', ''))[:60]}"
    if t in _OUTCOME:
        return f"■ {_OUTCOME[t]} · {str(e.get('summary') or e.get('reason') or e.get('question') or '')[:80]}"
    return f"  · {t}"
