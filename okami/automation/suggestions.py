"""Suggestions proativas CONSENT-FIRST (#8 item 2) — a superfície única de automação proposta.

O agente NOTA uma rotina ("você pede o resumo do dia toda manhã") e PROPÕE agendá-la; nada roda sem o
dono ACEITAR (aí vira um cron job de verdade, reusando o Scheduler). Dispensar LATCHA: a mesma
`dedup_key` nunca é re-oferecida (não vira nag). Cap de pendentes p/ não virar parede de propostas.
Persistência: `<root>/.okami/suggestions.json`.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

_CAP = 5   # máx. de sugestões PENDENTES ao mesmo tempo (anti-nag, igual ao MAX_PENDING do Hermes)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "sug"


class SuggestionStore:
    def __init__(self, root):
        self.path = Path(root) / ".okami" / "suggestions.json"

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("items", [])
        except (OSError, ValueError):
            return []

    def _save(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)   # atômico

    def add(self, *, text: str, schedule: str, prompt: str, dedup_key: str = "", source: str = "agent") -> str | None:
        """Registra uma proposta PENDENTE. Devolve o id, ou None se dedup (latched) ou fila cheia."""
        items = self._load()
        key = str(dedup_key).strip() or _slug(text)
        if any(it.get("dedup_key") == key for it in items):       # já oferecida/aceita/dispensada → não re-oferece
            return None
        if sum(1 for it in items if it.get("status") == "pending") >= _CAP:
            return None
        ids = {it["id"] for it in items}
        sid, base, i = _slug(key), _slug(key), 2
        while sid in ids:
            sid, i = f"{base}-{i}", i + 1
        items.append({"id": sid, "text": str(text), "schedule": str(schedule), "prompt": str(prompt),
                      "dedup_key": key, "source": source, "status": "pending", "created_at": time.time()})
        self._save(items)
        return sid

    def pending(self) -> list[dict]:
        return [it for it in self._load() if it.get("status") == "pending"]

    def _resolve(self, sid: str, status: str) -> dict | None:
        items = self._load()
        hit = None
        for it in items:
            if it["id"] == sid and it.get("status") == "pending":
                it["status"], hit = status, it
        if hit:
            self._save(items)
        return hit

    def dismiss(self, sid: str) -> bool:
        """Dispensa (LATCHA a dedup_key — nunca mais re-oferecida)."""
        return bool(self._resolve(sid, "dismissed"))

    def accept(self, sid: str, scheduler) -> dict | None:
        """Aceita → cria o cron job de verdade no `scheduler`. None se id desconhecido/não-pendente."""
        it = self._resolve(sid, "accepted")
        if not it:
            return None
        try:
            return scheduler.add(it["schedule"], it["prompt"])
        except Exception:  # noqa: BLE001 — falha do scheduler não corrompe o store (já marcou accepted)
            return None


# ── Catálogo de STARTERS (Hermes suggestion_catalog): 4 rotinas comuns p/ semear de primeira ──
STARTERS = [
    {"text": "quer um resumo do dia toda manhã às 8h?", "schedule": "0 8 * * *",
     "prompt": "Faça um resumo do que importa hoje (agenda, e-mails importantes, pendências) e me entregue.",
     "dedup_key": "daily-briefing"},
    {"text": "quer que eu monitore e-mails importantes a cada 2h?", "schedule": "every 2h",
     "prompt": "Cheque e-mails importantes/urgentes não lidos e me avise os que merecem atenção.",
     "dedup_key": "important-mail-monitor"},
    {"text": "quer uma revisão da semana toda sexta às 17h?", "schedule": "0 17 * * 5",
     "prompt": "Faça a revisão da semana: o que andou, o que ficou pendente, o que priorizar na próxima.",
     "dedup_key": "weekly-review"},
    {"text": "quer um lembrete de prioridades no início do expediente, 9h em dia útil?", "schedule": "0 9 * * 1-5",
     "prompt": "Bom dia — liste as 3 prioridades do dia com base no que está pendente.",
     "dedup_key": "workday-start"},
]


def seed_starters(store: SuggestionStore) -> int:
    """Semeia os STARTERS (dedup-aware: idempotente). Devolve quantos foram adicionados."""
    n = 0
    for st in STARTERS:
        if store.add(text=st["text"], schedule=st["schedule"], prompt=st["prompt"],
                     dedup_key=st["dedup_key"], source="catalog"):
            n += 1
    return n
