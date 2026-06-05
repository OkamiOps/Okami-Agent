"""Scheduling (§11) — cron + intervalos + one-shot, estilo OpenClaw/Hermes.

Persiste jobs em `<root>/.okami/cron.json`, decide o que está VENCIDO e executa pela MESMA máquina
de estados do harness (§3) — tarefa agendada também nunca trava. Formatos de schedule:
- **intervalo**: "30m", "1h", "2h30m", "90s", "every 1h".
- **cron** (5 campos: min hora dia mês diadassemana): "0 9 * * 1" (seg 9h), "*/15 * * * *".
- **one-shot**: ISO "2026-06-10T09:00" (roda uma vez).
O resultado é entregue de volta num chat (gateway) ou impresso (CLI). Clock injetável p/ teste.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

_INTERVAL_RE = re.compile(r"(\d+)\s*([smhd])")
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _slug(text: str) -> str:
    """Id CURTO de cron job a partir do prompt — tópico, não a frase literal do usuário (core.naming)."""
    from okami.core.naming import short_name
    return short_name(text, fallback="job")


def _parse_interval(spec: str) -> int | None:
    s = re.sub(r"\s+", "", spec.lower().replace("every", ""))
    if not s or not re.fullmatch(r"(\d+[smhd])+", s):     # aceita múltiplas unidades: "2h30m"
        return None
    return sum(int(n) * _UNIT[u] for n, u in _INTERVAL_RE.findall(s)) or None


def _parse_iso(spec: str) -> float | None:
    try:
        return datetime.fromisoformat(spec.replace("at ", "").strip()).timestamp()
    except (ValueError, TypeError):
        return None


def parse_schedule(spec: str) -> dict:
    """Classifica o schedule: {'kind': 'cron'|'interval'|'once', ...}."""
    spec = spec.strip()
    parts = spec.split()
    if len(parts) == 5 and all(re.fullmatch(r"[\d*/,\-]+", p) for p in parts):
        return {"kind": "cron", "expr": spec}
    secs = _parse_interval(spec)
    if secs:
        return {"kind": "interval", "seconds": secs}
    return {"kind": "once", "at": spec}


def _cron_field(field: str, value: int, lo: int) -> bool:
    if field == "*":
        return True
    for part in field.split(","):
        if part.startswith("*/"):
            step = int(part[2:])
            if step and (value - lo) % step == 0:
                return True
        elif "-" in part:
            a, b = part.split("-")
            if int(a) <= value <= int(b):
                return True
        elif part.isdigit() and int(part) == value:
            return True
    return False


def _cron_match(expr: str, dt: datetime) -> bool:
    mi, ho, dom, mo, dow = expr.split()
    cron_dow = (dt.weekday() + 1) % 7        # cron: 0=domingo; Python: 0=segunda
    return (_cron_field(mi, dt.minute, 0) and _cron_field(ho, dt.hour, 0)
            and _cron_field(dom, dt.day, 1) and _cron_field(mo, dt.month, 1)
            and _cron_field(dow, cron_dow, 0))


def is_due(schedule: str, now_ts: float, last_run: float | None) -> bool:
    s = parse_schedule(schedule)
    if s["kind"] == "interval":
        return last_run is None or (now_ts - last_run) >= s["seconds"]
    if s["kind"] == "cron":
        if not _cron_match(s["expr"], datetime.fromtimestamp(now_ts)):
            return False
        return last_run is None or int(last_run // 60) != int(now_ts // 60)   # 1x por minuto no máx.
    if s["kind"] == "once":
        target = _parse_iso(s["at"])
        return last_run is None and target is not None and now_ts >= target
    return False


def _time_phrase(low: str, now_ts: float) -> str | None:
    """Frase de tempo → schedule (ISO p/ one-shot relativo, cron p/ recorrente)."""
    m = re.search(r"daqui a (\d+)\s*(min|minuto|m|hora|h|dia|d)", low)
    if m:
        n, u = int(m.group(1)), m.group(2)[0]
        secs = n * {"m": 60, "h": 3600, "d": 86400}.get(u, 60)
        return datetime.fromtimestamp(now_ts + secs).isoformat(timespec="minutes")
    hora = re.search(r"\bas\s+(\d{1,2})\b", low) or re.search(r"\b(\d{1,2})\s*h\b", low)
    h = int(hora.group(1)) if hora else 9
    if "todo dia" in low or "todos os dias" in low or "diariamente" in low:
        return f"0 {h} * * *"                         # cron diário
    dias = {"segunda": 1, "terca": 2, "terça": 2, "quarta": 3, "quinta": 4, "sexta": 5,
            "sabado": 6, "sábado": 6, "domingo": 0}
    for nome, dow in dias.items():
        if f"toda {nome}" in low or f"todo {nome}" in low or f"todas as {nome}" in low:
            return f"0 {h} * * {dow}"                  # cron semanal
    if "amanha" in low or "amanhã" in low:
        return datetime.fromtimestamp(now_ts + 86400).replace(hour=h, minute=0,
                                                              second=0, microsecond=0).isoformat(timespec="minutes")
    return None


def infer_commitment(text: str, now_ts: float) -> tuple[str, str] | None:
    """Detecta um COMPROMISSO na fala ("me lembra de X amanhã", "todo dia às 9 faça Y") →
    (schedule, prompt) p/ virar um job. Estilo OpenClaw 'inferred commitments'. None se não houver."""
    import unicodedata
    low = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    if not re.search(r"\blembr|\blembrete|\bagend", low):     # gatilho explícito (evita falso-positivo)
        return None
    sched = _time_phrase(low, now_ts)
    if not sched:
        return None
    m = re.search(r"lembr\w*\s+(?:de\s+|que\s+|para\s+|pra\s+)?(.*)", text, re.IGNORECASE)
    action = (m.group(1) if m else text).strip().rstrip("?.! ")
    action = re.sub(r"\b(amanh[ãa]|hoje|daqui a \d+\s*\w+|todo dia|todos os dias|toda[s]?\s+\w+|"
                    r"[àa]s?\s*\d{1,2}\s*h?)\b", "", action, flags=re.IGNORECASE)
    action = re.sub(r"\s{2,}", " ", action).strip(" ,") or text.strip()
    return sched, action[:120]


class Scheduler:
    def __init__(self, root: str = ".", *, clock=time.time):
        self.path = Path(root) / ".okami" / "cron.json"
        self._clock = clock

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def save(self, jobs: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(jobs, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        os.replace(tmp, self.path)

    def add(self, schedule: str, prompt: str, agent: str | None = None, target: str | None = None) -> dict:
        jobs = self.load()
        base = _slug(prompt)
        jid, i = base, 2
        ids = {j["id"] for j in jobs}
        while jid in ids:
            jid, i = f"{base}-{i}", i + 1
        job = {"id": jid, "schedule": schedule, "kind": parse_schedule(schedule)["kind"],
               "prompt": prompt, "agent": agent, "target": target, "enabled": True, "last_run": None}
        jobs.append(job)
        self.save(jobs)
        return job

    def remove(self, jid: str) -> bool:
        jobs = self.load()
        kept = [j for j in jobs if j["id"] != jid]
        self.save(kept)
        return len(kept) != len(jobs)

    def set_enabled(self, jid: str, on: bool) -> None:
        jobs = self.load()
        for j in jobs:
            if j["id"] == jid:
                j["enabled"] = on
        self.save(jobs)

    def due(self, now_ts: float | None = None) -> list[dict]:
        now = now_ts if now_ts is not None else self._clock()
        return [j for j in self.load() if j.get("enabled", True)
                and is_due(j["schedule"], now, j.get("last_run"))]

    def mark_run(self, jid: str, now_ts: float | None = None) -> None:
        now = now_ts if now_ts is not None else self._clock()
        jobs = self.load()
        for j in jobs:
            if j["id"] == jid:
                j["last_run"] = now
                if j.get("kind") == "once":
                    j["enabled"] = False         # one-shot: desativa após rodar
        self.save(jobs)

    def tick(self, execute, now_ts: float | None = None) -> list[tuple[str, str]]:
        """Roda os jobs vencidos via `execute(job)->str`; marca cada um. Devolve [(id, resultado)]."""
        now = now_ts if now_ts is not None else self._clock()
        out = []
        for job in self.due(now):
            try:
                result = execute(job)
            except Exception as e:  # noqa: BLE001 — um job ruim não derruba o scheduler
                result = f"erro: {e}"
            self.mark_run(job["id"], now)
            out.append((job["id"], result))
        return out
