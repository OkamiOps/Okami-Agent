"""#19 canais regionais (paridade Hermes): DingTalk, WeCom (WeChat Work), QQBot — outbound notification."""
from __future__ import annotations


def test_dingtalk_send_and_outbound_only():
    from okami.channels.regional import DingTalkChannel
    ch = DingTalkChannel("tok123", "group1")
    sent = {}
    ch._post = lambda path, body: sent.update({"path": path, "body": body}) or {}
    ch.send("group1", "olá DingTalk")
    assert "access_token=tok123" in sent["path"]
    assert sent["body"]["text"]["content"] == "olá DingTalk" and sent["body"]["msgtype"] == "text"
    assert ch.poll() == []                                # outbound-only (inbound callback é follow-up)


def test_wecom_send():
    from okami.channels.regional import WeComChannel
    ch = WeComChannel("key-abc", "group1")
    sent = {}
    ch._post = lambda path, body: sent.update({"path": path, "body": body}) or {}
    ch.send("group1", "olá WeCom")
    assert "key=key-abc" in sent["path"] and sent["body"]["text"]["content"] == "olá WeCom"
    assert ch.poll() == []


def test_qqbot_send():
    from okami.channels.regional import QQBotChannel
    ch = QQBotChannel("apptoken", "ch9")
    sent = {}
    ch._post = lambda path, body: sent.update({"path": path, "body": body}) or {}
    ch.send("ch9", "olá QQ")
    assert "/channels/ch9/messages" in sent["path"] and sent["body"]["content"] == "olá QQ"
    assert ch.poll() == []


def test_regional_channels_deny_by_default():
    from okami.channels.regional import DingTalkChannel
    ch = DingTalkChannel("t", "g1")
    assert ch.allowed("qualquer") is False                # deny-by-default
    ch2 = DingTalkChannel("t", "g1", allow_all=True)
    assert ch2.allowed("qualquer") is True


def test_regional_channels_registered():
    from okami.gateway.channel_registry import REGISTRY
    assert {"dingtalk", "wecom", "qqbot"} <= set(REGISTRY)
    for name in ("dingtalk", "wecom", "qqbot"):
        assert REGISTRY[name].surface == name
