"""Parsers PUROS de inbound (#20) — payload da API/webhook de cada plataforma → list[Inbound].

Separados do canal p/ serem testáveis offline (sem rede). Cada parser ignora a PRÓPRIA mensagem do bot
(anti-loop) e mensagens vazias. Cobre os pollable (Signal/Matrix/BlueBubbles) e os webhook-push
(DingTalk/WeCom/QQBot/WhatsApp/SMS/Weixin).
"""
from __future__ import annotations

from okami.channels.base import Inbound

# ----------------------------------------------------------------- pollable


def parse_signal_receive(payload, *, self_number: str = "") -> list[Inbound]:
    """signal-cli `/v1/receive` → lista de envelopes. Texto em envelope.dataMessage.message."""
    out: list[Inbound] = []
    for item in (payload or []):
        env = (item or {}).get("envelope") or {}
        src = str(env.get("source") or env.get("sourceNumber") or "")
        msg = ((env.get("dataMessage") or {}).get("message") or "").strip()
        if not msg or (self_number and src == self_number):
            continue
        out.append(Inbound("signal", src, text=msg, msg_id=str(env.get("timestamp") or "")))
    return out


def parse_matrix_sync(payload, *, self_user: str = "") -> tuple[list[Inbound], str]:
    """Matrix `/sync` → (mensagens, next_batch). Eventos m.room.message de cada sala 'join'."""
    out: list[Inbound] = []
    payload = payload or {}
    joined = (((payload.get("rooms") or {}).get("join")) or {})
    for room_id, room in joined.items():
        for ev in (((room or {}).get("timeline") or {}).get("events") or []):
            if ev.get("type") != "m.room.message":
                continue
            sender = str(ev.get("sender") or "")
            if self_user and sender == self_user:
                continue
            body = ((ev.get("content") or {}).get("body") or "").strip()
            if not body:
                continue
            out.append(Inbound("matrix", str(room_id), text=body, msg_id=str(ev.get("event_id") or "")))
    return out, str(payload.get("next_batch") or "")


def parse_bluebubbles(payload) -> list[Inbound]:
    """BlueBubbles `/api/v1/message` → mensagens. Ignora isFromMe (anti-loop)."""
    out: list[Inbound] = []
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    for m in (data or []):
        if m.get("isFromMe"):
            continue
        text = (m.get("text") or "").strip()
        if not text:
            continue
        chat = str((m.get("handle") or {}).get("address") or m.get("chatGuid") or "")
        out.append(Inbound("bluebubbles", chat, text=text, msg_id=str(m.get("guid") or "")))
    return out


# ----------------------------------------------------------------- webhook-push (callback → Inbound)


def parse_dingtalk_webhook(body: dict) -> Inbound | None:
    """DingTalk callback: {msgtype:text, text:{content}, senderStaffId/conversationId}."""
    if (body or {}).get("msgtype") != "text":
        return None
    text = body.get("text")                                 # payload malformado pode mandar str → não crashar
    content = ((text.get("content") if isinstance(text, dict) else None) or "").strip()
    chat = str(body.get("conversationId") or body.get("senderStaffId") or body.get("senderNick") or "")
    return Inbound("dingtalk", chat, text=content, msg_id=str(body.get("msgId") or "")) if content else None


def parse_wecom_webhook(xml: str) -> Inbound | None:
    """WeCom/Weixin callback é XML: <xml><MsgType>text</MsgType><Content>..</Content><FromUserName>..</></xml>."""
    fields = _parse_simple_xml(xml)
    if (fields.get("MsgType") or "").lower() != "text":
        return None
    content = (fields.get("Content") or "").strip()
    chat = fields.get("FromUserName") or fields.get("FromUserID") or ""
    return Inbound("wecom", chat, text=content, msg_id=fields.get("MsgId", "")) if content else None


def parse_weixin_webhook(xml: str) -> Inbound | None:
    inb = parse_wecom_webhook(xml)
    if inb is not None:
        return Inbound("weixin", inb.chat_id, text=inb.text, msg_id=inb.msg_id)
    return None


def parse_qqbot_webhook(body: dict) -> Inbound | None:
    """QQ Bot callback: {id, content, author:{id}, channel_id}."""
    content = (body or {}).get("content")
    content = (content or "").strip() if isinstance(content, str) else ""
    chat = str(body.get("channel_id") or (body.get("author") or {}).get("id") or "")
    return Inbound("qqbot", chat, text=content, msg_id=str(body.get("id") or "")) if content else None


def parse_whatsapp_webhook(body: dict) -> Inbound | None:
    """WhatsApp Cloud API callback: entry[].changes[].value.messages[] {id,type:text,text:{body},from}."""
    for entry in (body or {}).get("entry", []) or []:
        for ch in (entry or {}).get("changes", []) or []:
            for m in ((ch.get("value") or {}).get("messages") or []):
                if m.get("type") != "text":
                    continue
                text = ((m.get("text") or {}).get("body") or "").strip()
                if text:
                    return Inbound("whatsapp", str(m.get("from") or ""), text=text, msg_id=str(m.get("id") or ""))
    # forma plana {messages:[{...}]}
    for m in (body or {}).get("messages", []) or []:
        text = ((m.get("text") or {}).get("body") or "").strip() if isinstance(m.get("text"), dict) else ""
        if text:
            return Inbound("whatsapp", str(m.get("from") or ""), text=text, msg_id=str(m.get("id") or ""))
    return None


def parse_sms_webhook(form: dict) -> Inbound | None:
    """SMS (Twilio-like): form {From, To, Body, MessageSid} ou {from,to,message}."""
    text = (form.get("Body") or form.get("body") or form.get("message") or "").strip()
    frm = form.get("From") or form.get("from") or ""
    return Inbound("sms", str(frm), text=text, msg_id=str(form.get("MessageSid") or form.get("id") or "")) if text else None


def _parse_simple_xml(xml: str) -> dict:
    """Extrai <Tag>valor</Tag> de um XML raso (tags-folha; CDATA ok) — regex, sem dep e sem expansão de
    entidade (anti-XXE/billion-laughs). O `[^<]*` garante folha → o <xml> externo não engole os filhos.
    Texto-plano (não-CDATA) é DECODIFICADO via html.unescape (&lt;→<, &amp;→&) — XML conforme escapa esses
    caracteres, então sem isto a mensagem chegaria com as entidades literais ao agente."""
    import html
    import re
    out: dict = {}
    for m in re.finditer(r"<(\w+)>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</\1>", xml or "", re.S):
        raw = m.group(2) if m.group(2) is not None else html.unescape(m.group(3) or "")
        out[m.group(1)] = raw.strip()
    return out


def webhook_parser(platform: str):
    """Devolve um `(body: bytes) -> Inbound|None` que decodifica o corpo do callback (JSON/XML/form) e
    chama o parser puro da plataforma. Usado pelo WebhookRoute.parser. None p/ plataforma desconhecida."""
    import json
    import urllib.parse

    def _json(body: bytes) -> dict:
        try:
            obj = json.loads((body or b"").decode("utf-8", "replace") or "{}")
            return obj if isinstance(obj, dict) else {}
        except (ValueError, AttributeError):
            return {}

    def _form(body: bytes) -> dict:
        return {k: v[0] for k, v in urllib.parse.parse_qs((body or b"").decode("utf-8", "replace")).items()}

    def _xml(body: bytes) -> str:
        return (body or b"").decode("utf-8", "replace")

    mapping = {
        "dingtalk": lambda b: parse_dingtalk_webhook(_json(b)),
        "wecom": lambda b: parse_wecom_webhook(_xml(b)),
        "weixin": lambda b: parse_weixin_webhook(_xml(b)),
        "qqbot": lambda b: parse_qqbot_webhook(_json(b)),
        "whatsapp": lambda b: parse_whatsapp_webhook(_json(b)),
        "sms": lambda b: parse_sms_webhook(_form(b)),
    }
    return mapping.get(platform)


__all__ = ["parse_signal_receive", "parse_matrix_sync", "parse_bluebubbles",
           "parse_dingtalk_webhook", "parse_wecom_webhook", "parse_weixin_webhook",
           "parse_qqbot_webhook", "parse_whatsapp_webhook", "parse_sms_webhook", "webhook_parser"]
