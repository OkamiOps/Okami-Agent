"""Canal Slack (§13 / #15) — REST polling de conversations.history; envia com chat.postMessage.

Bot token (xoxb-…). Lê SÓ o canal configurado, ignora as próprias mensagens (anti-loop). Mesma
interface Channel do Telegram (poll/send/allowed) → o gateway não muda.
"""

from __future__ import annotations

import time

from okami.channels._http import RestChannel
from okami.channels.base import Inbound


class SlackChannel(RestChannel):
    name = "slack"
    base_url = "https://slack.com/api"

    def __init__(self, token: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.token = token
        self._oldest = ""
        self._bot_id = ""

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def start(self) -> None:
        r = self._post("/auth.test", {})                 # descobre o próprio id (filtra anti-loop)
        self._bot_id = str(r.get("user_id") or r.get("bot_id") or "")
        self._oldest = f"{time.time():.6f}"              # só mensagens NOVAS (não relê o histórico)

    def poll(self) -> list[Inbound]:
        r = self._post("/conversations.history",
                       {"channel": self.channel_id, "oldest": self._oldest, "limit": 50})
        out: list[Inbound] = []
        for m in reversed(r.get("messages") or []):       # history vem do mais novo → ordem cronológica
            ts = m.get("ts", "")
            if ts:
                self._oldest = ts                         # avança o cursor (mesmo p/ msg ignorada)
            if m.get("bot_id") or m.get("subtype") or str(m.get("user") or "") == self._bot_id:
                continue                                  # próprio bot / sistema → ignora
            text = m.get("text")
            if text:
                out.append(Inbound("slack", self.channel_id, text=text, msg_id=str(ts)))
        return out

    MAX_LEN = 3900                                       # Slack rende mal/recusa msg muito longa → fatia

    def send(self, chat_id, text: str) -> None:
        for chunk in self._chunks(text):                # manda INTEIRO em partes (não trunca)
            res = self._post("/chat.postMessage", {"channel": str(chat_id), "text": chunk})
            if isinstance(res, dict) and res.get("ok") is False:   # 200 OK + {ok:false} → entrega FALHOU
                raise RuntimeError(f"Slack recusou o envio: {res.get('error') or 'erro'}")   # (não em silêncio)
