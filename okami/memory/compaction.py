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


_OBS_PREFIX = "OBSERVAÇÃO (passo "
_PRUNE_MIN = 400          # observação menor que isto não vale podar (a 1-linha não economizaria nada)


def prune_observations(messages: list[dict], *, keep_tail: int = 6,
                       min_chars: int = _PRUNE_MIN) -> tuple[list[dict], int]:
    """Fase 1 BARATA da compactação (pré-pass do Hermes, sem LLM): tool-results antigos viram
    1 linha informativa e saídas IDÊNTICAS repetidas são deduplicadas (apontando pro passo mais
    recente). A janela recente (keep_tail) fica intocada. Retorna (mensagens, chars_economizados).

    Sem perda real: o transcript bruto segue na sessão — aqui só sai do CONTEXTO do modelo."""
    import hashlib
    if len(messages) <= keep_tail + 1:
        return messages, 0
    out = list(messages)
    head_idx = range(1, len(out) - keep_tail)         # nunca o system (0) nem o tail
    # passada 1 (de trás pra frente): saída idêntica → a mais RECENTE vence; antigas viram ponteiro
    newest: dict[str, str] = {}                       # hash do corpo -> "passo N" mais recente
    dup: dict[int, str] = {}                          # índice antigo -> passo recente que tem o conteúdo
    for i in reversed(head_idx):
        c = out[i].get("content") or ""
        if not c.startswith(_OBS_PREFIX) or len(c) < min_chars:
            continue
        header, _, body = c.partition("\n")
        h = hashlib.md5(body.encode("utf-8", "ignore")).hexdigest()
        if h in newest:
            dup[i] = newest[h]
        else:
            newest[h] = header[len(_OBS_PREFIX):].split(",", 1)[0]   # "N" do passo
    saved = 0
    for i in head_idx:
        c = out[i].get("content") or ""
        if not c.startswith(_OBS_PREFIX) or len(c) < min_chars:
            continue
        header = c.partition("\n")[0]
        if i in dup:
            short = (f"{header}\n[saída idêntica à do passo {dup[i]} — deduplicada; "
                     "use a versão mais recente]")
        else:
            short = (f"{header}\n[podado: {len(c)} chars saíram do contexto; o conteúdo bruto "
                     "segue no transcript da sessão — refaça a leitura se precisar dele]")
        if len(short) < len(c):
            saved += len(c) - len(short)
            out[i] = {**out[i], "content": short}
    return out, saved


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
