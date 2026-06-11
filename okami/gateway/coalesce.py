"""Coalescing de entrada (paridade OpenClaw inbound-debounce, versão por-lote): rajada de mensagens
de TEXTO do mesmo chat que chegou no MESMO poll (paste partido, pensamento em 4 msgs seguidas) vira
UM turno do agente — junta com \\n, na posição da primeira, com o msg_id da última.

NÃO se misturam: comandos (/x), mensagens com mídia (audio/image/file) e chats diferentes. Mídia no
meio QUEBRA o agrupamento do chat (ordem temporal preservada — "antes da foto" ≠ "depois da foto")."""

from __future__ import annotations

from dataclasses import replace

from okami.channels.base import Inbound


def _mergeable(m: Inbound) -> bool:
    return (bool(m.text) and not m.text.lstrip().startswith("/")
            and not m.audio and not m.image and not getattr(m, "file", None))


def coalesce_inbound(msgs: list[Inbound]) -> list[Inbound]:
    out: list[Inbound] = []
    open_idx: dict[str, int] = {}      # chat_id → índice em `out` do grupo de texto ABERTO desse chat
    for m in msgs:
        cid = str(m.chat_id)
        if not _mergeable(m):
            open_idx.pop(cid, None)    # comando/mídia fecha o grupo deste chat (ordem preservada)
            out.append(m)
            continue
        if cid in open_idx:
            prev = out[open_idx[cid]]
            out[open_idx[cid]] = replace(prev, text=f"{prev.text}\n{m.text}",
                                         msg_id=m.msg_id or prev.msg_id)
        else:
            open_idx[cid] = len(out)
            out.append(m)
    return out
