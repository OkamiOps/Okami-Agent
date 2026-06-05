"""Canais Slack/Discord/Mattermost (#15): poll filtra o próprio bot, send posta, deny-by-default,
e build_endpoints constrói um endpoint por canal configurado."""

from __future__ import annotations

from pathlib import Path

from okami.channels.discord import DiscordChannel
from okami.channels.mattermost import MattermostChannel
from okami.channels.slack import SlackChannel


def test_slack_poll_filters_bot_and_send_posts(monkeypatch):
    ch = SlackChannel("xoxb-tok", "C123", allow_all=True)
    ch._bot_id = "UBOT"
    hist = {"messages": [
        {"ts": "3", "user": "UBOT", "text": "minha própria fala"},     # do bot → ignora
        {"ts": "2", "subtype": "channel_join", "text": "entrou"},      # sistema → ignora
        {"ts": "1", "user": "UHUMAN", "text": "oi okami"},             # humano → vira Inbound
    ]}
    sent = {}
    monkeypatch.setattr(ch, "_post", lambda path, body: sent.update({path: body}) or hist)
    inb = ch.poll()
    assert len(inb) == 1 and inb[0].text == "oi okami" and inb[0].channel == "slack"
    ch.send("C123", "resposta")
    assert sent["/chat.postMessage"] == {"channel": "C123", "text": "resposta"}


def test_discord_poll_filters_bot_authors(monkeypatch):
    ch = DiscordChannel("tok", "999", allow_all=True)
    ch._bot_id = "BID"
    msgs = [
        {"id": "30", "author": {"id": "BID", "bot": True}, "content": "minha"},   # próprio → ignora
        {"id": "29", "author": {"id": "OTHERBOT", "bot": True}, "content": "bot"},  # outro bot → ignora
        {"id": "28", "author": {"id": "HUMAN"}, "content": "oi"},                  # humano → Inbound
    ]
    sent = {}
    monkeypatch.setattr(ch, "_get", lambda path, params=None: msgs)
    monkeypatch.setattr(ch, "_post", lambda path, body: sent.update({path: body}))
    inb = ch.poll()
    assert len(inb) == 1 and inb[0].text == "oi" and ch._after == "30"   # cursor avança p/ o mais novo
    ch.send("999", "ola")
    assert sent["/channels/999/messages"] == {"content": "ola"}


def test_mattermost_poll_filters_self_and_system(monkeypatch):
    ch = MattermostChannel("https://mm.ex.com", "tok", "chanid", allow_all=True)
    ch._bot_id = "BOT"
    r = {"order": ["p3", "p2", "p1"], "posts": {
        "p3": {"create_at": 300, "user_id": "BOT", "message": "minha"},          # próprio → ignora
        "p2": {"create_at": 200, "user_id": "U", "type": "system_join", "message": "x"},  # sistema → ignora
        "p1": {"create_at": 100, "user_id": "U", "message": "oi mm"},            # humano → Inbound
    }}
    sent = {}
    monkeypatch.setattr(ch, "_get", lambda path, params=None: r)
    monkeypatch.setattr(ch, "_post", lambda path, body: sent.update({path: body}))
    inb = ch.poll()
    assert len(inb) == 1 and inb[0].text == "oi mm" and ch._since == 300
    ch.send("chanid", "resp")
    assert sent["/posts"] == {"channel_id": "chanid", "message": "resp"}
    assert ch.base_url.endswith("/api/v4")


def test_deny_by_default_but_configured_channel_allowed():
    ch = SlackChannel("t", "C1")                       # sem allowlist
    assert ch.allowed("C1") is True                    # o canal configurado é o opt-in
    assert ch.allowed("OUTRO") is False                # qualquer outro → deny
    assert DiscordChannel("t", "9", allow_all=True).allowed("qualquer") is True


def test_build_endpoints_wires_each_configured_channel():
    from okami.agents import AgentSpec
    from okami.gateway import build_endpoints
    from tests.test_gateway import _runner_ok
    specs = {"a": AgentSpec("a", Path("."), {"channels": {
        "slack": {"token": "x", "channel_id": "C1", "allow_all": True},
        "mattermost": {"base_url": "https://mm", "token": "y", "channel_id": "m1", "allow_all": True},
    }})}
    graw = {"default_provider": "lmstudio", "providers": {"lmstudio": {"model": "openai/x", "api_key": "k"}}}
    eps = build_endpoints(graw, specs, run_task=_runner_ok)
    names = sorted(e.channel.name for e in eps)
    assert names == ["mattermost", "slack"]            # um endpoint por canal configurado
