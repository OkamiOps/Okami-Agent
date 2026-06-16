"""Canais de mensageria que faltavam (#19, paridade Hermes) — WhatsApp, Signal, Matrix, SMS, BlueBubbles,
Weixin. OUTBOUND (notificação): o agente publica/manda mensagem via a API de cada plataforma. `poll()`=[]
(o inbound de cada uma — webhook/sync/daemon — é um épico próprio); aqui já entregamos o outbound útil
(alerta/relatório/cron). Mesma interface Channel, deny-by-default. `_post` mockável → testado sem rede.
"""
from __future__ import annotations

from okami.channels.regional import _OutboundChannel


class WhatsAppChannel(_OutboundChannel):
    """WhatsApp Cloud API (Meta) — POST /<phone_id>/messages."""
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


class SignalChannel(_OutboundChannel):
    """Signal via signal-cli-rest-api (daemon local) — POST /v2/send."""
    name = "signal"

    def __init__(self, api_url: str, number: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.base_url = api_url.rstrip("/")
        self.number = number

    def send(self, chat_id, text: str) -> None:
        self._post("/v2/send", {"number": self.number, "recipients": [str(chat_id)], "message": text})


class MatrixChannel(_OutboundChannel):
    """Matrix (client-server API) — POST /_matrix/client/v3/rooms/<room>/send/m.room.message."""
    name = "matrix"

    def __init__(self, homeserver: str, token: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.base_url = homeserver.rstrip("/")
        self.token = token

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def send(self, chat_id, text: str) -> None:
        self._post(f"/_matrix/client/v3/rooms/{chat_id}/send/m.room.message",
                   {"msgtype": "m.text", "body": text})


class SMSChannel(_OutboundChannel):
    """SMS via gateway HTTP genérico (Twilio-like / provedor próprio) — POST /send {to, message}."""
    name = "sms"

    def __init__(self, api_url: str, from_number: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.base_url = api_url.rstrip("/")
        self.from_number = from_number

    def send(self, chat_id, text: str) -> None:
        self._post("/send", {"from": self.from_number, "to": str(chat_id), "message": text})


class BlueBubblesChannel(_OutboundChannel):
    """iMessage via BlueBubbles server (local) — POST /api/v1/message/text."""
    name = "bluebubbles"

    def __init__(self, server_url: str, password: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.base_url = server_url.rstrip("/")
        self.password = password

    def send(self, chat_id, text: str) -> None:
        self._post(f"/api/v1/message/text?password={self.password}",
                   {"chatGuid": str(chat_id), "message": text, "method": "apple-script"})


class WeixinChannel(_OutboundChannel):
    """WeChat (conta oficial) — mensagem de atendimento POST /cgi-bin/message/custom/send."""
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
