"""Coalescing de entrada (paridade OpenClaw inbound-debounce, versão por-lote): rajada de mensagens
do mesmo chat no MESMO poll vira UM turno do agente.

- TEXTO: paste partido / pensamento em 4 msgs seguidas → junta com \\n.
- FOTOS (#11): álbum / rajada de fotos → 1 turno com todas as imagens + legendas mescladas (antes só a
  última chegava). Mídia de tipos DIFERENTES (audio/file) e comando (/x) seguem quebrando o grupo.

Chats diferentes nunca se misturam; a ordem temporal é preservada.
"""

from __future__ import annotations

from dataclasses import replace

from okami.channels.base import Inbound


def _text_mergeable(m: Inbound) -> bool:
    return (bool(m.text) and not m.text.lstrip().startswith("/")
            and not m.audio and not m.image and not m.images and not getattr(m, "file", None))


def _image_mergeable(m: Inbound) -> bool:
    return (bool(m.image or m.images) and not m.audio and not getattr(m, "file", None)
            and not (m.text and m.text.lstrip().startswith("/")))


def _imgs_of(m: Inbound) -> list[str]:
    return list(m.images) if m.images else ([m.image] if m.image else [])


def merge_caption(existing: str, new: str) -> str:
    """Mescla legendas dedupando por bloco (não-substring): 'Reunião' não vira 'Reunião\\n\\nReunião'."""
    ex = (existing or "").strip()
    nw = (new or "").strip()
    if not nw:
        return ex
    if not ex:
        return nw
    blocks = [b.strip() for b in ex.split("\n\n")]
    if nw in blocks:
        return ex
    return ex + "\n\n" + nw


def coalesce_inbound(msgs: list[Inbound]) -> list[Inbound]:
    out: list[Inbound] = []
    open_idx: dict[str, tuple[int, str]] = {}      # chat_id → (índice em out, tipo do grupo aberto)
    for m in msgs:
        cid = str(m.chat_id)
        if _text_mergeable(m):
            kind = "text"
        elif _image_mergeable(m):
            kind = "image"
        else:
            open_idx.pop(cid, None)               # comando/audio/file fecha o grupo deste chat
            out.append(m)
            continue
        cur = open_idx.get(cid)
        if cur and cur[1] == kind:
            prev = out[cur[0]]
            if kind == "text":
                out[cur[0]] = replace(prev, text=f"{prev.text}\n{m.text}", msg_id=m.msg_id or prev.msg_id)
            else:                                  # rajada de fotos: acumula imagens + mescla legendas
                imgs = _imgs_of(prev)
                for im in _imgs_of(m):
                    if im not in imgs:
                        imgs.append(im)
                out[cur[0]] = replace(prev, images=imgs, image=imgs[0] if imgs else None,
                                      text=merge_caption(prev.text, m.text), msg_id=m.msg_id or prev.msg_id)
        else:
            if kind == "image":                    # normaliza p/ lista (corrige o caminho single→list)
                imgs = _imgs_of(m)
                m = replace(m, images=imgs, image=imgs[0] if imgs else None)
            open_idx[cid] = (len(out), kind)
            out.append(m)
    return out
