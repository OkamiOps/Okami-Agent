"""Memória em CAMADAS — combina vários backends (§6).

É o daily-driver do user: **holographic (local, rápido) + honcho (user-model remoto)**.
Write faz fan-out; inject concatena os blocos (cada camada contribui o seu); recall faz merge
com dedup. Uma camada que falha (ex.: Honcho offline) não derruba as outras.
"""

from __future__ import annotations

from okami.memory.base import Memory, MemoryItem


class LayeredMemory(Memory):
    def __init__(self, backends: list[Memory]):
        self.backends = backends

    def write(self, item: MemoryItem) -> int:
        first = 0
        for b in self.backends:
            try:
                rid = b.write(item)
                first = first or rid
            except Exception:  # noqa: BLE001
                pass
        return first

    def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        seen: set[str] = set()
        out: list[MemoryItem] = []
        for b in self.backends:
            try:
                items = b.recall(query, limit)
            except Exception:  # noqa: BLE001
                items = []
            for it in items:
                key = it.text.strip()[:120].lower()
                if key and key not in seen:
                    seen.add(key)
                    out.append(it)
        out.sort(key=lambda i: -((i.score if i.score is not None else 0.0)))
        return out[:limit]

    def inject(self, query: str = "", limit: int = 5) -> str:
        """Mesmo tratamento que `recall` já tem: concatenar o bloco INTEIRO de cada backend duplicava
        preâmbulo (cada camada traz o seu) e dobrava o volume injetado (2x tokens, mesma info, cada
        backend já respeita `limit` sozinho). Aqui trata a 1ª linha de cada bloco multi-linha como
        HEADER (usa só a do primeiro backend que tiver um) e o resto como ITENS — dedup por chave
        (120 primeiros chars, igual ao recall) e cap total em `limit` itens combinados → UM preâmbulo."""
        preamble = ""
        seen: set[str] = set()
        items: list[str] = []
        for b in self.backends:
            try:
                blk = b.inject(query, limit)
            except Exception:  # noqa: BLE001
                blk = ""
            if not blk:
                continue
            blk_lines = blk.splitlines()
            head, rest = (blk_lines[0], blk_lines[1:]) if len(blk_lines) > 1 else ("", blk_lines)
            if head and not preamble:
                preamble = head
            for line in rest:
                key = line.strip()[:120].lower()
                if key and key not in seen:
                    seen.add(key)
                    items.append(line)
        if not preamble and not items:
            return ""
        capped = items[:limit]
        return "\n".join(([preamble] if preamble else []) + capped)

    def recent(self, limit: int = 10) -> list[MemoryItem]:
        out: list[MemoryItem] = []
        for b in self.backends:
            try:
                out.extend(b.recent(limit))
            except Exception:  # noqa: BLE001
                pass
        return out[:limit]

    def count(self) -> int:
        total = 0
        for b in self.backends:
            try:
                total += b.count()
            except Exception:  # noqa: BLE001
                pass
        return total

    def health(self) -> dict:
        """Agrega a saúde de cada camada (P2). `ok=False` se uma camada `required` falhou."""
        layers = []
        for b in self.backends:
            try:
                layers.append(b.health())
            except Exception:  # noqa: BLE001
                layers.append({"backend": type(b).__name__, "ok": True, "failures": 0})
        bad_required = [h for h in layers if h.get("required") and not h.get("ok", True)]
        return {"backend": "layered", "ok": not bad_required, "layers": layers}

    def forget(self, max_items: int = 500) -> int:
        n = 0
        for b in self.backends:
            try:
                n += b.forget(max_items)
            except Exception:  # noqa: BLE001
                pass
        return n

    def consolidate(self, now: float | None = None) -> dict:
        out = {"expired": 0, "merged": 0}
        for b in self.backends:
            try:
                r = b.consolidate(now)
                out["expired"] += int(r.get("expired", 0))
                out["merged"] += int(r.get("merged", 0))
            except Exception:  # noqa: BLE001
                pass
        return out

    def close(self) -> None:
        for b in self.backends:
            try:
                b.close()
            except Exception:  # noqa: BLE001
                pass
