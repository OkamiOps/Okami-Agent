"""GroupEndpoint — um GRUPO multi-agente sobre um canal (§10/§13)."""

from __future__ import annotations

import time
from typing import Callable

from okami.gateway.sessions import TranscriptStore


class GroupEndpoint:
    """Um GRUPO multi-agente sobre um canal (§10/§13): escuta o chat, roda o `GroupRoom` em cada
    mensagem HUMANA e cada agente responde PELA SUA PRÓPRIA token. O anti-stampede vem do GroupRoom
    (moderador decide quem fala/ninguém + cooldown + caps). Síncrono e ordenado: um burst por vez —
    mensagens que chegam durante um burst esperam no canal e entram no próximo poll."""

    def __init__(self, room, channel, *, label: str = "group", min_delay: float = 0.0,
                 store_root: str = ".", emit: Callable[[str], None] = lambda m: None):
        self.room = room              # GroupRoom (membros + moderador + responder)
        self.channel = channel        # poll() / send_as(agent_id, chat_id, text) / allowed()
        self.label = label
        self.min_delay = min_delay     # pausa entre falas (parece humano; 0 nos testes)
        self.emit = emit
        self.running = True
        self._started = False
        self.store = TranscriptStore(store_root, subdir="groups")   # transcript do grupo (2 camadas §13)
        self._hydrate()               # restart: recarrega a conversa e os cooldowns do disco

    def _hydrate(self) -> None:
        """Restart: rebuild da conversa do grupo + estado de turn-taking (turn/cooldowns)."""
        self.room.history = self.store.history(self.label, limit=40)
        e = self.store.entry(self.label)
        self.room.turn = int(e.get("turn", 0))
        self.room.bot_streak = 0      # humano sempre zera; não faz sentido persistir streak
        cds = e.get("cooldowns") or {}
        for m in self.room.members:
            m.cooldown_until = int(cds.get(m.id, 0))

    def _save_state(self) -> None:
        self.store.update_entry(self.label, turn=self.room.turn,
                                cooldowns={m.id: m.cooldown_until for m in self.room.members})

    def handle(self, chat_id, text: str, mentioned=None) -> list[tuple[str, str]]:
        if not self.channel.allowed(chat_id):
            return []
        self.store.append(self.label, "USER", text)    # transcript append-only (sobrevive a restart)
        replies = self.room.dispatch("USER", text, mentioned=mentioned)
        for agent_id, reply in replies:
            self.channel.send_as(agent_id, chat_id, reply)
            self.store.append(self.label, agent_id, reply)   # cada fala de agente vira um nó (papel=id)
            if self.min_delay:
                time.sleep(self.min_delay)
        if not replies:
            self.emit(f"[{self.label}] ninguém se manifestou (sem stampede)")
        self._save_state()
        return replies

    def poll_once(self) -> None:
        from okami.agents.group import parse_mentions
        for msg in self.channel.poll():                 # canal já filtra mensagens dos próprios bots
            if not msg.text:
                continue
            mentioned = parse_mentions(msg.text, {m.id for m in self.room.members})
            self.handle(msg.chat_id, msg.text, mentioned=mentioned)

    def loop(self) -> None:
        if not self._started:
            try:
                self.channel.start()
            except Exception:  # noqa: BLE001
                pass
            self._started = True
        while self.running:
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001 — rede instável não derruba o grupo
                time.sleep(3)
