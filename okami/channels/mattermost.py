"""Canal Mattermost (§13 / #15) — REST polling de /channels/{id}/posts?since; envia POST /posts.

Self-hosted: precisa de `base_url` (servidor) + bot token. Lê SÓ o canal configurado, ignora o próprio
post e mensagens de sistema (anti-loop).
"""

from __future__ import annotations

import time

from okami.channels._http import RestChannel
from okami.channels.base import Inbound


class MattermostChannel(RestChannel):
    name = "mattermost"

    def __init__(self, base_url: str, token: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.base_url = base_url.rstrip("/") + "/api/v4"
        self.token = token
        self._since = 0
        self._bot_id = ""

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def start(self) -> None:
        self._bot_id = str((self._get("/users/me") or {}).get("id") or "")
        self._since = int(time.time() * 1000)            # ms — só posts NOVOS

    def poll(self) -> list[Inbound]:
        r = self._get(f"/channels/{self.channel_id}/posts", {"since": self._since})
        posts = r.get("posts") or {}
        out: list[Inbound] = []
        for pid in reversed(r.get("order") or []):        # order vem do mais novo → cronológico
            p = posts.get(pid) or {}
            ca = int(p.get("create_at") or 0)
            if ca > self._since:
                self._since = ca
            if str(p.get("user_id") or "") == self._bot_id or p.get("type"):
                continue                                  # próprio bot / sistema → ignora
            msg = p.get("message")
            if msg:
                out.append(Inbound("mattermost", self.channel_id, text=msg, msg_id=str(pid)))
        return out

    def send(self, chat_id, text: str) -> None:
        self._post("/posts", {"channel_id": str(chat_id), "message": text})
