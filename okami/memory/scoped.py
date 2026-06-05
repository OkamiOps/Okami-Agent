"""Memória COM ESCOPO (#3) — roteia ESCRITA por escopo e LÊ dos dois stores.

`scope=global` (preferência do usuário) → casa `~/.okami`; o resto → o projeto. recall/inject/recent
leem AMBOS: a preferência global entra em QUALQUER projeto, mas a memória de um projeto NÃO contamina
outro (cada projeto tem seu próprio store local). Uma camada que falha não derruba a outra.
"""

from __future__ import annotations

from okami.memory.base import Memory, MemoryItem


def _is_global(item: MemoryItem) -> bool:
    return (getattr(item, "scope", "") or "").strip().lower().startswith("global")


class ScopedMemory(Memory):
    def __init__(self, project: Memory, global_: Memory):
        self.project = project
        self.global_ = global_

    def write(self, item: MemoryItem) -> int:
        return (self.global_ if _is_global(item) else self.project).write(item)

    def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        seen: set[str] = set()
        out: list[MemoryItem] = []
        for b in (self.global_, self.project):       # global primeiro: preferência do usuário ancora
            try:
                items = b.recall(query, limit)
            except Exception:  # noqa: BLE001
                items = []
            for it in items:
                k = it.text.strip()[:120].lower()
                if k and k not in seen:
                    seen.add(k)
                    out.append(it)
        out.sort(key=lambda i: -(i.score if i.score is not None else 0.0))
        return out[:limit]

    def recent(self, limit: int = 10) -> list[MemoryItem]:
        out: list[MemoryItem] = []
        for b in (self.global_, self.project):
            try:
                out.extend(b.recent(limit))
            except Exception:  # noqa: BLE001
                pass
        return out[:limit]

    def inject(self, query: str = "", limit: int = 5) -> str:
        blocks = []
        for b in (self.global_, self.project):
            try:
                blk = b.inject(query, limit)
            except Exception:  # noqa: BLE001
                blk = ""
            if blk:
                blocks.append(blk)
        return "\n\n".join(blocks)

    def count(self) -> int:
        n = 0
        for b in (self.global_, self.project):
            try:
                n += b.count()
            except Exception:  # noqa: BLE001
                pass
        return n

    # ── CRUD por id: tenta o projeto, depois a casa (o id pertence a um dos dois) ──
    def forget_item(self, item_id: int) -> bool:
        return bool(self.project.forget_item(item_id) or self.global_.forget_item(item_id))

    def archive_item(self, item_id: int) -> bool:
        return bool(self.project.archive_item(item_id) or self.global_.archive_item(item_id))

    def explain(self, item_id: int) -> dict | None:
        return self.project.explain(item_id) or self.global_.explain(item_id)

    def export(self) -> list[dict]:
        return list(self.project.export()) + list(self.global_.export())

    def health(self) -> dict:
        layers = []
        for b in (self.project, self.global_):
            try:
                layers.append(b.health())
            except Exception:  # noqa: BLE001
                layers.append({"backend": type(b).__name__, "ok": True})
        return {"backend": "scoped", "ok": all(h.get("ok", True) for h in layers), "layers": layers}

    def forget(self, max_items: int = 500) -> int:
        n = 0
        for b in (self.project, self.global_):
            try:
                n += b.forget(max_items)
            except Exception:  # noqa: BLE001
                pass
        return n

    def consolidate(self, now: float | None = None) -> dict:
        out = {"expired": 0, "merged": 0}
        for b in (self.project, self.global_):
            try:
                r = b.consolidate(now)
                out["expired"] += int(r.get("expired", 0))
                out["merged"] += int(r.get("merged", 0))
            except Exception:  # noqa: BLE001
                pass
        return out

    def close(self) -> None:
        for b in (self.project, self.global_):
            try:
                b.close()
            except Exception:  # noqa: BLE001
                pass
