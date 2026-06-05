"""Interface de memória (§6). Backends intercambiáveis implementam `Memory`.

Ciclo de vida (espelha o Hermes): inject (no prompt) → prefetch/recall (antes do turno) →
write (sync/mirror) → reflect (curadoria). O agente não sabe qual backend está ativo.
"""

from __future__ import annotations

from dataclasses import dataclass


def is_secret_item(item) -> bool:
    """True se o item NÃO deve persistir (contém segredo) — gate COMUM a todo backend (#P1).

    A política prepare() já recusa nos callers explícitos; mas compaction/learning chamam
    memory.write() DIRETO. Este gate, chamado no topo de cada backend.write(), fecha o bypass."""
    from okami.core.redact import looks_secret
    text = item if isinstance(item, str) else getattr(item, "text", "")
    if looks_secret(text):
        from okami import log
        log.warn("memory: bloqueei escrita de item com cara de segredo (write direto/compaction/learning).")
        return True
    return False


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
        """Bloco de memória relevante para o system prompt, COM citação de origem (#11)."""
        from okami.memory.citation import cited_line
        items = self.recall(query, limit) if query.strip() else self.recent(limit)
        # inclui as categorias da write policy (#10): preferência/decisão/skill/erro ancoram a resposta.
        relevant = ("fact", "preference", "decision", "skill", "error", "summary", "anti_pattern", "lesson")
        items = [i for i in items if i.kind in relevant] or items
        if not items:
            return ""
        lines = ["O QUE VOCÊ JÁ SABE (ancore a resposta nisto — cada item traz [categoria · origem · "
                 "confiança]; NÃO recite as tags nem diga 'na memória consta'):"]
        lines += [cited_line(i) for i in items]
        return "\n".join(lines)

    def reflect(self) -> None:  # curadoria/dreaming (opcional)
        return None

    def health(self) -> dict:
        """Saúde da camada (P2): {backend, ok, failures, last_error}. Backend resiliente sobrescreve."""
        return {"backend": type(self).__name__, "ok": True, "failures": 0, "last_error": ""}

    def close(self) -> None:
        return None
