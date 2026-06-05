"""Canal Discord (§13 / #15) — REST polling de /channels/{id}/messages; envia POST no mesmo canal.

Bot token (`Authorization: Bot <token>`). Lê SÓ o canal configurado, ignora bots/o próprio (anti-loop).
"""

from __future__ import annotations

from okami.channels._http import RestChannel
from okami.channels.base import Inbound


class DiscordChannel(RestChannel):
    name = "discord"
    base_url = "https://discord.com/api/v10"

    def __init__(self, token: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.token = token
        self._after = "0"
        self._bot_id = ""

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bot {self.token}"}

    def start(self) -> None:
        self._bot_id = str((self._get("/users/@me") or {}).get("id") or "")
        latest = self._get(f"/channels/{self.channel_id}/messages", {"limit": 1})   # só mensagens NOVAS
        if isinstance(latest, list) and latest:
            self._after = str(latest[0].get("id") or "0")

    def poll(self) -> list[Inbound]:
        msgs = self._get(f"/channels/{self.channel_id}/messages", {"after": self._after, "limit": 50})
        out: list[Inbound] = []
        for m in reversed(msgs if isinstance(msgs, list) else []):   # vem do mais novo → cronológico
            mid = str(m.get("id") or "")
            if mid:
                self._after = mid
            au = m.get("author") or {}
            if au.get("bot") or str(au.get("id") or "") == self._bot_id:
                continue                                   # bot / próprio → ignora (anti-loop)
            text = m.get("content")
            if text:
                out.append(Inbound("discord", self.channel_id, text=text))
        return out

    def send(self, chat_id, text: str) -> None:
        self._post(f"/channels/{chat_id}/messages", {"content": text})
