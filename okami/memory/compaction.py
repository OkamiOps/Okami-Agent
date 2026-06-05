"""Auto-compaction sem perder contexto (§6.4).

Princípio: compaction = PROMOVER para long-term + deixar ponteiro recuperável, nunca esquecer.
Antes de comprimir, as mensagens antigas são escritas no backend de memória (recuperáveis via
recall_memory); só então são substituídas por um resumo com ponteiro.
"""

from __future__ import annotations

from okami.memory.base import Memory, MemoryItem


def estimate_chars(messages: list[dict]) -> int:
    return sum(len(m.get("content") or "") for m in messages)


def compact(messages: list[dict], memory: Memory | None, *,
            keep_tail: int = 6, source: str = "compaction") -> tuple[list[dict], int]:
    """Retorna (mensagens_compactadas, n_promovidas). Mantém system + últimas keep_tail."""
    if len(messages) <= keep_tail + 2:
        return messages, 0
    system = messages[0]
    head = messages[1:-keep_tail]
    tail = messages[-keep_tail:]

    promoted = 0
    if memory is not None:
        from okami.memory.base import is_secret_item
        for m in head:
            content = (m.get("content") or "").strip()
            if not content:
                continue
            item = MemoryItem(text=f"[{m.get('role', '?')}] {content}", kind="turn", source=source)
            if is_secret_item(item):      # segredo NÃO persiste → não infla a contagem de promovidas
                continue
            memory.write(item)
            promoted += 1
        note = (f"RESUMO (auto-compaction): {promoted} mensagens antigas foram PROMOVIDAS à "
                "memória de longo prazo e são recuperáveis com a tool recall_memory. "
                "Nada foi perdido — continue.")
    else:
        note = (f"RESUMO (auto-compaction): {len(head)} mensagens antigas foram resumidas "
                "(sem backend de memória ativo). Continue.")
    return [system, {"role": "user", "content": note}, *tail], promoted
