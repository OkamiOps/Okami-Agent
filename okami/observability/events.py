"""Event log estruturado por task (JSONL) — estilo Hermes (observabilidade/replay).

Toda a vida da task vira uma linha JSON em `.okami/events.jsonl`: start, step (tool/ok),
violation, loop, escalate, compact, memory_write, complete/blocked/need_input. É a base do
replay/debug (`okami events`). Best-effort: NUNCA derruba o turno; segredos são mascarados.
"""

from __future__ import annotations

import itertools
import json
import time
from pathlib import Path
from typing import Any


class EventLog:
    """Append-only de eventos da task em `.okami/<name>.jsonl` (seq monotônico + ts + redação)."""

    def __init__(self, workspace: Path, *, name: str = "events") -> None:
        self._path = Path(workspace) / ".okami" / f"{name}.jsonl"
        self._seq = itertools.count(1)

    @property
    def path(self) -> Path:
        return self._path

    def emit(self, type: str, **data: Any) -> None:
        try:
            from okami.core.redact import redact
            self._path.parent.mkdir(parents=True, exist_ok=True)
            rec = {"seq": next(self._seq), "ts": round(time.time(), 3), "type": type, **data}
            line = json.dumps(rec, ensure_ascii=False, default=str)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(redact(line) + "\n")
        except Exception:  # noqa: BLE001 — observabilidade nunca derruba o turno
            pass


def read_events(workspace: Path, *, name: str = "events") -> list[dict]:
    """Lê o timeline (p/ replay/debug). Linhas inválidas são ignoradas (best-effort)."""
    p = Path(workspace) / ".okami" / f"{name}.jsonl"
    if not p.exists():
        return []
    out: list[dict] = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out
