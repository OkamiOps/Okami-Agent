"""Canais de mensageria (#19/#20) — WhatsApp, Signal, Matrix, SMS, BlueBubbles, Weixin.

Signal/Matrix/BlueBubbles têm INBOUND real (`poll()` — endpoint de receive/sync); WhatsApp/SMS/Weixin são
outbound (inbound via webhook → okami/channels/webhook.py + inbound_parsers). Todos têm send(). `_post`/`_get`
mockáveis → testado sem rede. deny-by-default herdado.
"""
from __future__ import annotations

from okami.channels._http import RestChannel
from okami.channels.base import Inbound
from okami.channels.regional import _OutboundChannel


class WhatsAppChannel(_OutboundChannel):
    """WhatsApp Cloud API (Meta) — POST /<phone_id>/messages. Inbound via webhook (parse_whatsapp_webhook)."""
    name = "whatsapp"
    base_url = "https://graph.facebook.com/v19.0"

    def __init__(self, token: str, phone_id: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.token = token
        self.phone_id = phone_id

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def send(self, chat_id, text: str) -> None:
        self._post(f"/{self.phone_id}/messages",
                   {"messaging_product": "whatsapp", "to": str(chat_id), "type": "text",
                    "text": {"body": text}})


class SignalChannel(RestChannel):
    """Signal via signal-cli-rest-api (daemon local). poll() = GET /v1/receive/<number> (destrutivo)."""
    name = "signal"
    poll_interval = 2.0

    def __init__(self, api_url: str, number: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.base_url = api_url.rstrip("/")
        self.number = number

    def send(self, chat_id, text: str) -> None:
        self._post("/v2/send", {"number": self.number, "recipients": [str(chat_id)], "message": text})

    def poll(self) -> list[Inbound]:
        from okami.channels.inbound_parsers import parse_signal_receive
        try:
            data = self._get(f"/v1/receive/{self.number}")
        except Exception:  # noqa: BLE001 — rede instável não derruba o poll
            return []
        return parse_signal_receive(data, self_number=self.number)


class MatrixChannel(RestChannel):
    """Matrix (client-server API). poll() = GET /sync incremental (since-token)."""
    name = "matrix"
    poll_interval = 1.0

    def __init__(self, homeserver: str, token: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.base_url = homeserver.rstrip("/")
        self.token = token
        self._since = ""
        self._self_user = ""

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def start(self) -> None:
        try:                                               # descobre o próprio id (anti-loop)
            self._self_user = str((self._get("/_matrix/client/v3/account/whoami") or {}).get("user_id") or "")
        except Exception:  # noqa: BLE001
            pass
        try:                                               # baseline: captura a posição atual sem reprocessar backlog
            self._since = str((self._get("/_matrix/client/v3/sync", {"timeout": "0"}) or {}).get("next_batch") or "")
        except Exception:  # noqa: BLE001
            pass

    def send(self, chat_id, text: str) -> None:
        self._post(f"/_matrix/client/v3/rooms/{chat_id}/send/m.room.message",
                   {"msgtype": "m.text", "body": text})

    def poll(self) -> list[Inbound]:
        from okami.channels.inbound_parsers import parse_matrix_sync
        try:
            r = self._get("/_matrix/client/v3/sync", {"since": self._since, "timeout": "1000"})
        except Exception:  # noqa: BLE001
            return []
        msgs, nxt = parse_matrix_sync(r, self_user=self._self_user)
        if nxt:
            self._since = nxt
        return msgs


class SMSChannel(_OutboundChannel):
    """SMS via gateway HTTP genérico. Inbound via webhook (parse_sms_webhook)."""
    name = "sms"

    def __init__(self, api_url: str, from_number: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.base_url = api_url.rstrip("/")
        self.from_number = from_number

    def send(self, chat_id, text: str) -> None:
        self._post("/send", {"from": self.from_number, "to": str(chat_id), "message": text})


class BlueBubblesChannel(RestChannel):
    """iMessage via BlueBubbles server (local). poll() = GET /api/v1/message (dedup por guid)."""
    name = "bluebubbles"
    poll_interval = 2.0

    def __init__(self, server_url: str, password: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.base_url = server_url.rstrip("/")
        self.password = password
        self._seen: dict[str, None] = {}                   # dict (ordem de inserção) → LRU mantém os MAIS recentes
        self._primed = False                               # baseline já capturado? (start() OU 1º poll)

    def send(self, chat_id, text: str) -> None:
        self._post(f"/api/v1/message/text?password={self.password}",
                   {"chatGuid": str(chat_id), "message": text, "method": "apple-script"})

    def _remember(self, guids) -> None:
        for g in guids:
            if g:
                self._seen[g] = None
        if len(self._seen) > 2000:                         # poda mantendo os 1000 guids MAIS RECENTES
            self._seen = dict(list(self._seen.items())[-1000:])

    def start(self) -> None:
        try:                                               # baseline: marca o backlog atual como visto
            data = (self._get(f"/api/v1/message?password={self.password}&limit=50") or {}).get("data", [])
            self._remember(m.get("guid") for m in data)
            self._primed = True                            # GET ok → baseline capturado
        except Exception:  # noqa: BLE001
            pass                                           # falhou → _primed segue False; o 1º poll baseliza

    def poll(self) -> list[Inbound]:
        from okami.channels.inbound_parsers import parse_bluebubbles
        try:
            data = self._get(f"/api/v1/message?password={self.password}&limit=50")
        except Exception:  # noqa: BLE001
            return []
        parsed = parse_bluebubbles(data)
        if not self._primed:                               # start() não rodou/falhou → baseliza tardiamente,
            self._remember(m.msg_id for m in parsed)       # sem despejar o backlog inteiro como "novo"
            self._primed = True
            return []
        fresh = [m for m in parsed if m.msg_id and m.msg_id not in self._seen]
        self._remember(m.msg_id for m in fresh)
        return fresh


class WeixinChannel(_OutboundChannel):
    """WeChat (conta oficial). Inbound via webhook XML (parse_weixin_webhook)."""
    name = "weixin"
    base_url = "https://api.weixin.qq.com"

    def __init__(self, access_token: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.access_token = access_token

    def send(self, chat_id, text: str) -> None:
        self._post(f"/cgi-bin/message/custom/send?access_token={self.access_token}",
                   {"touser": str(chat_id), "msgtype": "text", "text": {"content": text}})


__all__ = ["WhatsAppChannel", "SignalChannel", "MatrixChannel", "SMSChannel",
           "BlueBubblesChannel", "WeixinChannel"]
