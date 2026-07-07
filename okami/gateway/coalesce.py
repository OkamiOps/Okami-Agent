"""Coalescing de entrada (paridade OpenClaw inbound-debounce): rajada de mensagens do mesmo chat vira
UM turno do agente.

- TEXTO: paste partido / pensamento em 4 msgs seguidas → junta com \\n.
- FOTOS (#11): álbum / rajada de fotos → 1 turno com todas as imagens + legendas mescladas (antes só a
  última chegava). Mídia de tipos DIFERENTES (audio/file) e comando (/x) seguem quebrando o grupo.
- JANELA DE TEMPO (fix #3): `coalesce_inbound` só junta rajadas do MESMO poll (mesmo lote). `WindowCoalescer`
  estende isso: 2 mensagens do mesmo chat chegando em POLLS diferentes, com <3s de intervalo, ainda
  viram 1 turno — cobre o caso comum de "escreveu, mandou, lembrou de algo, mandou de novo" onde os dois
  envios caem em ciclos de poll distintos.

Chats diferentes nunca se misturam; a ordem temporal é preservada.
"""

from __future__ import annotations

import time
from dataclasses import replace

from okami.channels.base import Inbound

# Janela do debounce por tempo (fix #3) quando LIGADO — paridade com o grace period do Hermes/OpenClaw.
COALESCE_WINDOW_SECONDS = 3.0

# Default é DESLIGADO (0.0): segurar toda mensagem única por até 3s pra ver se mais alguma coisa chega
# adicionaria latência perceptível ao caso comum (1 mensagem → 1 turno), o que é exatamente o tipo de
# regressão de responsividade que este projeto já caçou antes. O debounce por janela é opt-IN via
# channels.coalesce_window (true → usa COALESCE_WINDOW_SECONDS; número → janela custom).
DEFAULT_COALESCE_WINDOW = 0.0


def _text_mergeable(m: Inbound) -> bool:
    return (bool(m.text) and not m.text.lstrip().startswith("/")
            and not m.audio and not m.image and not m.images and not getattr(m, "file", None))


def _image_mergeable(m: Inbound) -> bool:
    return (bool(m.image or m.images) and not m.audio and not getattr(m, "file", None)
            and not (m.text and m.text.lstrip().startswith("/")))


def _merge_kind(m: Inbound) -> str | None:
    """'text' | 'image' | None (não-mesclável: comando, áudio, arquivo)."""
    if _text_mergeable(m):
        return "text"
    if _image_mergeable(m):
        return "image"
    return None


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


def _merge_one(prev: Inbound, m: Inbound, kind: str) -> Inbound:
    """Mescla `m` dentro do grupo aberto `prev` (mesmo `kind`) — usado tanto pelo merge por-lote
    (coalesce_inbound) quanto pelo merge por-janela (WindowCoalescer)."""
    if kind == "text":
        return replace(prev, text=f"{prev.text}\n{m.text}", msg_id=m.msg_id or prev.msg_id)
    imgs = _imgs_of(prev)                          # rajada de fotos: acumula imagens + mescla legendas
    for im in _imgs_of(m):
        if im not in imgs:
            imgs.append(im)
    return replace(prev, images=imgs, image=imgs[0] if imgs else None,
                    text=merge_caption(prev.text, m.text), msg_id=m.msg_id or prev.msg_id)


def coalesce_inbound(msgs: list[Inbound]) -> list[Inbound]:
    out: list[Inbound] = []
    open_idx: dict[str, tuple[int, str]] = {}      # chat_id → (índice em out, tipo do grupo aberto)
    for m in msgs:
        cid = str(m.chat_id)
        kind = _merge_kind(m)
        if kind is None:
            open_idx.pop(cid, None)               # comando/audio/file fecha o grupo deste chat
            out.append(m)
            continue
        cur = open_idx.get(cid)
        if cur and cur[1] == kind:
            out[cur[0]] = _merge_one(out[cur[0]], m, kind)
        else:
            if kind == "image":                    # normaliza p/ lista (corrige o caminho single→list)
                imgs = _imgs_of(m)
                m = replace(m, images=imgs, image=imgs[0] if imgs else None)
            open_idx[cid] = (len(out), kind)
            out.append(m)
    return out


class WindowCoalescer:
    """Coalescing por JANELA DE TEMPO (fix #3): estende `coalesce_inbound` (que só junta rajadas do
    MESMO poll) pra rajadas que atravessam ciclos de poll diferentes — 2 mensagens mescláveis do mesmo
    chat com <`window`s de intervalo entre elas ainda viram 1 turno, mesmo vindo em `feed()` separados.

    Mensagem só é LIBERADA (aparece no retorno de `feed()`) quando:
      - chega uma mensagem NÃO-mesclável (comando/áudio/arquivo) pro mesmo chat (fecha o grupo na hora); ou
      - passam `window` segundos desde a última atualização daquele chat sem mensagem nova (grace period
        esgotado — liberado no PRÓXIMO `feed()`, mesmo que venha vazio).

    `window <= 0` desliga o debounce por tempo (vira equivalente a chamar `coalesce_inbound` por lote,
    sem segurar nada entre polls) — é o default (ver DEFAULT_COALESCE_WINDOW).
    """

    def __init__(self, window: float = DEFAULT_COALESCE_WINDOW):
        self.window = window
        self._pending: dict[str, Inbound] = {}
        self._last_seen: dict[str, float] = {}

    def _flush_chat(self, cid: str, ready: list[Inbound]) -> None:
        m = self._pending.pop(cid, None)
        self._last_seen.pop(cid, None)
        if m is not None:
            ready.append(m)

    def feed(self, msgs: list[Inbound], now: float | None = None) -> list[Inbound]:
        """Alimenta o lote deste poll (pode ser vazio, só pra destravar grupos que esfriaram) e devolve
        as mensagens PRONTAS pra virar turno agora."""
        now = time.monotonic() if now is None else now
        ready: list[Inbound] = []
        if self.window <= 0:                        # opt-out (default): sem estado entre polls
            ready.extend(coalesce_inbound(msgs))
            return ready
        for m in coalesce_inbound(msgs):             # merge por-lote primeiro (rajada no MESMO poll)
            cid = str(m.chat_id)
            kind = _merge_kind(m)
            if kind is None:                         # não-mesclável → fecha o que tava pendente e passa direto
                self._flush_chat(cid, ready)
                ready.append(m)
                continue
            prev = self._pending.get(cid)
            if (prev is not None and _merge_kind(prev) == kind
                    and (now - self._last_seen.get(cid, 0.0)) <= self.window):
                self._pending[cid] = _merge_one(prev, m, kind)
            else:
                self._flush_chat(cid, ready)         # grupo antigo (se algum) sai antes do novo entrar
                if kind == "image":
                    imgs = _imgs_of(m)
                    m = replace(m, images=imgs, image=imgs[0] if imgs else None)
                self._pending[cid] = m
            self._last_seen[cid] = now
        for cid in list(self._pending):               # libera quem esfriou (sem msg nova neste poll)
            if now - self._last_seen.get(cid, 0.0) > self.window:
                self._flush_chat(cid, ready)
        return ready
