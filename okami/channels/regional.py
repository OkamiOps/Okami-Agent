"""Canais regionais asiáticos (#19, paridade Hermes) — DingTalk, WeCom (WeChat Work), QQBot.

Notificação OUTBOUND: o agente PUBLICA num grupo/canal (o caso de bot mais comum nessas plataformas) via
o webhook/bot API de cada uma. `poll()` devolve [] — o inbound delas é callback-push com cripto de
assinatura (épico próprio); aqui entregamos o outbound já útil (alerta/relatório/cron). Mesma interface
Channel, deny-by-default herdado do RestChannel. `_post` é mockável → testado sem rede.
"""
from __future__ import annotations

from okami.channels._http import RestChannel
from okami.channels.base import Inbound


class _OutboundChannel(RestChannel):
    """Base dos canais outbound-only: poll() vazio; send() implementado por cada um."""

    def poll(self) -> list[Inbound]:
        return []


class DingTalkChannel(_OutboundChannel):
    name = "dingtalk"
    base_url = "https://oapi.dingtalk.com"

    def __init__(self, token: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.token = token

    def send(self, chat_id, text: str) -> None:
        self._post(f"/robot/send?access_token={self.token}",
                   {"msgtype": "text", "text": {"content": text}})


class WeComChannel(_OutboundChannel):
    """WeChat Work (WeCom) — bot webhook (`/cgi-bin/webhook/send?key=…`)."""
    name = "wecom"
    base_url = "https://qyapi.weixin.qq.com"

    def __init__(self, key: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.key = key

    def send(self, chat_id, text: str) -> None:
        self._post(f"/cgi-bin/webhook/send?key={self.key}",
                   {"msgtype": "text", "text": {"content": text}})


class QQBotChannel(_OutboundChannel):
    """QQ Official Bot — posta mensagem num canal (`/channels/<id>/messages`)."""
    name = "qqbot"
    base_url = "https://api.sgroup.qq.com"

    def __init__(self, token: str, channel_id, *, allow_chats=None, allow_all: bool = False):
        super().__init__(channel_id, allow_chats=allow_chats, allow_all=allow_all)
        self.token = token

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bot {self.token}"}

    def send(self, chat_id, text: str) -> None:
        self._post(f"/channels/{chat_id}/messages", {"content": text})


__all__ = ["DingTalkChannel", "WeComChannel", "QQBotChannel"]
