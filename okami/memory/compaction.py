"""Auto-compaction sem perder contexto (§6.4).

Princípio (P2 — separação de camadas): a SESSÃO guarda o histórico BRUTO (transcript recuperável);
a MEMÓRIA guarda só FATOS DURÁVEIS. Compaction NÃO despeja turno bruto na memória (log/IDs/progresso
efêmero virariam "fato" e contaminariam o recall) — cada mensagem antiga passa pelo FILTRO SEMÂNTICO
(memory.policy: classifica fato/decisão/preferência/skill/erro, barra temp/trivial/segredo). Só o que
é durável é destilado; o resto sai do contexto mas continua no transcript da sessão.
"""

from __future__ import annotations

from okami.memory.base import Memory


def estimate_chars(messages: list[dict]) -> int:
    return sum(len(m.get("content") or "") for m in messages)


def compact(messages: list[dict], memory: Memory | None, *,
            keep_tail: int = 6, source: str = "compaction") -> tuple[list[dict], int]:
    """Retorna (mensagens_compactadas, n_destiladas). Mantém system + últimas keep_tail.

    n_destiladas = fatos DURÁVEIS escritos na memória (não nº de mensagens) — o histórico bruto
    completo segue recuperável na sessão (transcript), não na memória semântica."""
    if len(messages) <= keep_tail + 2:
        return messages, 0
    system = messages[0]
    head = messages[1:-keep_tail]
    tail = messages[-keep_tail:]

    distilled = 0
    if memory is not None:
        from okami.memory.policy import prepare
        for m in head:
            content = (m.get("content") or "").strip()
            if not content:
                continue
            # filtro semântico: turno BRUTO não vira memória. Só fato/decisão/preferência/skill/erro
            # durável (classificado, não-segredo, não-efêmero) é destilado — com a categoria certa.
            item = prepare(content, source=f"{source}:{m.get('role', '?')}")
            if item is None:                          # log/ID/progresso efêmero/segredo → fica só na sessão
                continue
            memory.write(item)
            distilled += 1
        note = (f"RESUMO (auto-compaction): {len(head)} mensagens antigas saíram do contexto; "
                f"{distilled} fato(s) durável(is) foram DESTILADOS à memória (recall_memory). "
                "O histórico bruto continua na sessão — nada foi perdido. Continue.")
    else:
        note = (f"RESUMO (auto-compaction): {len(head)} mensagens antigas saíram do contexto "
                "(sem backend de memória ativo; histórico segue na sessão). Continue.")
    # A nota é 'user'. Se tail[0] também for 'user', sairiam DUAS 'user' seguidas — OpenAI tolera, mas
    # Anthropic/Claude EXIGE alternância (erro de API). Funde a nota no 1º do tail nesse caso.
    if tail and tail[0].get("role") == "user":
        merged = {**tail[0], "content": note + "\n\n" + (tail[0].get("content") or "")}
        return [system, merged, *tail[1:]], distilled
    return [system, {"role": "user", "content": note}, *tail], distilled
