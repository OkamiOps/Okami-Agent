"""Interface de memória (§6). Backends intercambiáveis implementam `Memory`.

Ciclo de vida (espelha o Hermes): inject (no prompt) → prefetch/recall (antes do turno) →
write (sync/mirror) → reflect (curadoria). O agente não sabe qual backend está ativo.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MemoryItem:
    text: str
    kind: str = "fact"        # fact | turn | decision | summary | procedural
    source: str = ""
    tags: str = ""
    ts: float = 0.0
    importance: float | None = None   # 0..1 (heurística/LLM); None = calcular
    last_access: float = 0.0
    access_count: int = 0
    id: int | None = None
    score: float | None = None        # score de retrieval (preenchido no recall)


class Memory:
    """Interface comum dos backends de memória."""

    def write(self, item: MemoryItem) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:  # pragma: no cover
        raise NotImplementedError

    def recent(self, limit: int = 10) -> list[MemoryItem]:  # pragma: no cover
        raise NotImplementedError

    def count(self) -> int:  # pragma: no cover
        raise NotImplementedError

    def inject(self, query: str = "", limit: int = 5) -> str:
        """Bloco de memória relevante para o system prompt."""
        items = self.recall(query, limit) if query.strip() else self.recent(limit)
        relevant = ("fact", "decision", "summary", "anti_pattern", "lesson")
        items = [i for i in items if i.kind in relevant] or items
        if not items:
            return ""
        lines = ["MEMÓRIA RELEVANTE (de sessões/contexto anterior):"]
        lines += [f"- {i.text.strip()[:200]}" for i in items]
        return "\n".join(lines)

    def reflect(self) -> None:  # curadoria/dreaming (opcional)
        return None

    def close(self) -> None:
        return None
