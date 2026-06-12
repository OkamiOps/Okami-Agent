"""Insights — analytics histórico cross-sessão (pesquisa #6 item 21, porta do insights do Hermes).

Agrega os eventos `llm_call` do event log (provider/model/surface/tokens/ts) por período: total +
breakdown por DIA, MODELO, PROVIDER e PLATAFORMA (surface). É o agregador que faltava — os dados já
são coletados pelo harness a cada chamada. Best-effort: event log ausente → relatório zerado.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

_DAY = 86400.0


def _bucket() -> dict:
    return {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cache": 0}


def _add(b: dict, e: dict) -> None:
    b["calls"] += 1
    b["tokens_in"] += int(e.get("tokens_in") or 0)
    b["tokens_out"] += int(e.get("tokens_out") or 0)
    b["cache"] += int(e.get("cache") or 0)


def collect(workspace, *, days: int = 30, now=time.time) -> dict:
    """Agrega o event log dos últimos `days` dias. now injetável p/ teste."""
    from okami.observability.events import read_events
    cutoff = now() - max(1, days) * _DAY
    rep = {"days": days, "calls": 0, "tokens_in": 0, "tokens_out": 0, "cache": 0,
           "by_model": {}, "by_provider": {}, "by_surface": {}, "by_day": {}}
    for e in read_events(Path(workspace)):
        if e.get("type") != "llm_call":
            continue
        ts = float(e.get("ts") or 0)
        if ts < cutoff:
            continue
        _add(rep, e)                                  # type: ignore[arg-type]  (rep tem os 4 contadores no topo)
        for dim, key in (("by_model", e.get("model") or "?"),
                         ("by_provider", e.get("provider") or "?"),
                         ("by_surface", e.get("surface") or "?")):
            _add(rep[dim].setdefault(key, _bucket()), e)
        day = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
        _add(rep["by_day"].setdefault(day, _bucket()), e)
    return rep


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _top(d: dict, k: int = 5) -> list[tuple[str, dict]]:
    return sorted(d.items(), key=lambda kv: kv[1]["tokens_in"] + kv[1]["tokens_out"], reverse=True)[:k]


def render(rep: dict) -> str:
    """Texto humano do relatório (multi-seção). Vazio → mensagem amigável."""
    if not rep.get("calls"):
        return f"📊 sem chamadas registradas nos últimos {rep.get('days', 30)} dias."
    lines = [f"📊 últimos {rep['days']} dias · {rep['calls']} chamadas · "
             f"{_fmt(rep['tokens_in'])} in / {_fmt(rep['tokens_out'])} out"
             + (f" · {_fmt(rep['cache'])} cache" if rep["cache"] else "")]

    def _section(title: str, d: dict):
        if not d:
            return
        lines.append(f"\n{title}:")
        for name, b in _top(d):
            lines.append(f"  {name}: {b['calls']}× · {_fmt(b['tokens_in'])} in / {_fmt(b['tokens_out'])} out")

    _section("por modelo", rep["by_model"])
    _section("por provider", rep["by_provider"])
    _section("por plataforma", rep["by_surface"])
    if rep["by_day"]:
        lines.append("\npor dia:")
        for day in sorted(rep["by_day"])[-7:]:
            b = rep["by_day"][day]
            lines.append(f"  {day}: {b['calls']}× · {_fmt(b['tokens_in'] + b['tokens_out'])} tok")
    return "\n".join(lines)
