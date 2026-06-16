"""#19 canais de mensageria que faltavam (paridade Hermes) — WhatsApp, Signal, Matrix, SMS, BlueBubbles,
Weixin. Outbound (notificação); send() mockável → testado sem rede."""
from __future__ import annotations


def _spy(ch):
    sent = {}
    ch._post = lambda path, body: sent.update({"path": path, "body": body}) or {}
    return sent


def test_whatsapp_send():
    from okami.channels.messaging import WhatsAppChannel
    ch = WhatsAppChannel("tok", "phone123", "+5511999")
    sent = _spy(ch)
    ch.send("+5511999", "oi WhatsApp")
    assert "/phone123/messages" in sent["path"]
    assert sent["body"]["text"]["body"] == "oi WhatsApp" and sent["body"]["to"] == "+5511999"
    assert ch.poll() == [] and ch.allowed("x") is False


def test_signal_send():
    from okami.channels.messaging import SignalChannel
    ch = SignalChannel("http://localhost:8080", "+1555", "+1666")
    sent = _spy(ch)
    ch.send("+1666", "oi Signal")
    assert "/v2/send" in sent["path"] and sent["body"]["message"] == "oi Signal"
    assert "+1666" in sent["body"]["recipients"]


def test_matrix_send():
    from okami.channels.messaging import MatrixChannel
    ch = MatrixChannel("https://matrix.org", "syt-token", "!room:matrix.org")
    sent = _spy(ch)
    ch.send("!room:matrix.org", "oi Matrix")
    assert "/rooms/!room:matrix.org/send/m.room.message" in sent["path"]
    assert sent["body"]["body"] == "oi Matrix" and sent["body"]["msgtype"] == "m.text"


def test_sms_send():
    from okami.channels.messaging import SMSChannel
    ch = SMSChannel("https://sms.gw/api", "+1000", "+1222")
    sent = _spy(ch)
    ch.send("+1222", "oi SMS")
    assert sent["body"]["to"] == "+1222" and sent["body"]["message"] == "oi SMS"


def test_bluebubbles_send():
    from okami.channels.messaging import BlueBubblesChannel
    ch = BlueBubblesChannel("http://localhost:1234", "pw", "chatguid1")
    sent = _spy(ch)
    ch.send("chatguid1", "oi iMessage")
    assert "/api/v1/message/text" in sent["path"] and sent["body"]["message"] == "oi iMessage"


def test_weixin_send():
    from okami.channels.messaging import WeixinChannel
    ch = WeixinChannel("access-tok", "openid1")
    sent = _spy(ch)
    ch.send("openid1", "oi WeChat")
    assert "access_token=access-tok" in sent["path"]
    assert sent["body"]["text"]["content"] == "oi WeChat" and sent["body"]["touser"] == "openid1"


def test_all_messaging_channels_registered():
    from okami.gateway.channel_registry import REGISTRY
    assert {"whatsapp", "signal", "matrix", "sms", "bluebubbles", "weixin"} <= set(REGISTRY)


def test_messaging_surfaces_in_tool_policy():
    from okami.core.tool_policy import _DENY_BY_SURFACE
    for s in ("whatsapp", "signal", "matrix", "sms", "bluebubbles", "weixin"):
        assert s in _DENY_BY_SURFACE
