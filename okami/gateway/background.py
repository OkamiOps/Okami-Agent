"""Registro PERSISTIDO de tarefas /background — durável (sobrevive a restart/crash do gateway).

Antes o /background só vivia em memória (self._bg): caiu o gateway, sumiu o estado. Aqui cada job é
gravado em `<ws>/.okami/background.json` com id/prompt/estado/tempos/resultado. No boot, job que ficou
'running' (o processo morreu no meio) vira 'interrupted' (reconcile). `okami` mostra via /background
status. Poda jobs velhos (TTL). Best-effort: nunca derruba o turno.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def event_line_plain(e: dict) -> str:
    """Um evento do harness → 1 linha de texto puro (sem Rich) p/ o log do /background."""
    k = e.get("kind")
    if k == "step":
        args = e.get("args") or {}
        prev = ""
        for key in ("path", "cmd", "query", "url", "name", "text", "goal"):
            v = args.get(key)
            if isinstance(v, str) and v:
                prev = " " + v.replace("\n", " ")[:60]
                break
        return f"{'✓' if e.get('ok') else '✗'} {e.get('tool', '')}{prev}".rstrip()
    if k == "approval_request":
        return f"⚠ aprovação: {e.get('reason', '')}"
    if k == "loop":
        return f"⟲ loop (x{e.get('repeats', '?')})"
    if k == "escalate":
        return f"⬆ escalando: {e.get('why', '')}"
    if k == "compact":
        return f"⊟ compactando ({e.get('promoted', 0)} → memória)"
    if k == "complete_rejected":
        return "✗ ainda falta: " + ", ".join(e.get("missing", []))
    return ""


class BackgroundRegistry:
    def __init__(self, ws):
        self.path = Path(ws) / ".okami" / "background.json"

    # ── log AO VIVO por job (stream de stdout/progresso, persistido + paginável) ──
    def log_path(self, jid: int) -> Path:
        return self.path.parent / "background" / f"{jid}.log"

    def append_log(self, jid: int, line: str) -> None:
        if not line:
            return
        p = self.log_path(jid)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(line.rstrip() + "\n")
        except OSError:
            pass

    def tail(self, jid: int, n: int = 30) -> list[str]:
        try:
            return self.log_path(jid).read_text(encoding="utf-8", errors="ignore").splitlines()[-max(1, n):]
        except OSError:
            return []

    def _read(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) and isinstance(d.get("jobs"), list) else {"seq": 0, "jobs": []}
        except (OSError, ValueError):
            return {"seq": 0, "jobs": []}

    def _write(self, d: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8", newline="\n")
        except OSError:
            pass

    def add(self, prompt: str, *, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        d = self._read()
        d["seq"] = int(d.get("seq", 0)) + 1
        jid = d["seq"]
        d["jobs"].append({"id": jid, "prompt": (prompt or "")[:200], "state": "running",
                          "started_at": now, "finished_at": None, "result": ""})
        self._write(d)
        return jid

    def finish(self, jid: int, *, state: str, result: str = "", now: float | None = None) -> None:
        now = now if now is not None else time.time()
        d = self._read()
        for j in d["jobs"]:
            if j.get("id") == jid:
                j.update(state=state, finished_at=now, result=(result or "")[:500])
                break
        self._write(d)

    def reconcile(self, *, now: float | None = None) -> int:
        """No boot: job 'running' (processo morreu) → 'interrupted'. Devolve quantos."""
        now = now if now is not None else time.time()
        d = self._read()
        n = 0
        for j in d["jobs"]:
            if j.get("state") == "running":
                j.update(state="interrupted", finished_at=now)
                n += 1
        if n:
            self._write(d)
        return n

    def list(self, limit: int = 20) -> list[dict]:
        return list(reversed(self._read()["jobs"]))[:limit]

    def running(self) -> list[dict]:
        return [j for j in self._read()["jobs"] if j.get("state") == "running"]

    def prune(self, *, keep: int = 50, max_age_days: float = 7.0, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        d = self._read()
        jobs = d["jobs"]
        cutoff = now - max_age_days * 86400

        def _fresh(j):
            fin = j.get("finished_at")
            return j.get("state") == "running" or (fin if fin is not None else now) >= cutoff

        alive = [j for j in jobs if _fresh(j)]
        d["jobs"] = alive[-keep:] if len(alive) > keep else alive
        removed = len(jobs) - len(d["jobs"])
        if removed:
            kept = {j.get("id") for j in d["jobs"]}
            for j in jobs:                               # apaga o log dos jobs podados (não deixa lixo)
                if j.get("id") not in kept:
                    try:
                        self.log_path(j["id"]).unlink(missing_ok=True)
                    except OSError:
                        pass
            self._write(d)
        return removed
