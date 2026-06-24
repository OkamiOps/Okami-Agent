"""Entrega SILENCIOSA falha (hunt#2): Slack/Discord/Mattermost devolvem 200 OK + corpo de ERRO
({"ok": false} / {"code": ...} / {"status_code": 4xx}). O send() ignorava o corpo → o dono achava que a
resposta foi entregue e nunca chegou ('o bot não funciona'). Agora send() levanta exceção → endpoint avisa."""
from __future__ import annotations

import pytest

from okami.channels.discord import DiscordChannel
from okami.channels.mattermost import MattermostChannel
from okami.channels.slack import SlackChannel


def _wire(ch, resp):
    ch._post = lambda *a, **k: resp
    return ch


def test_slack_send_raises_on_not_ok():
    ch = _wire(SlackChannel("xoxb-FAKE", "C1", allow_all=True), {"ok": False, "error": "channel_not_found"})
    with pytest.raises(Exception) as e:
        ch.send("C1", "oi")
    assert "channel_not_found" in str(e.value)


def test_slack_send_ok_does_not_raise():
    _wire(SlackChannel("xoxb-FAKE", "C1", allow_all=True), {"ok": True, "ts": "1"}).send("C1", "oi")


def test_discord_send_raises_on_error_code():
    ch = _wire(DiscordChannel("FAKE", "123", allow_all=True), {"code": 50001, "message": "Missing Access"})
    with pytest.raises(Exception) as e:
        ch.send("123", "oi")
    assert "Missing Access" in str(e.value)


def test_discord_send_ok_does_not_raise():
    _wire(DiscordChannel("FAKE", "123", allow_all=True), {"id": "999"}).send("123", "oi")


def test_mattermost_send_raises_on_status_code():
    ch = _wire(MattermostChannel("https://mm.example", "FAKE", "ch1", allow_all=True),
               {"status_code": 403, "id": "api.context.permissions.app_error", "message": "forbidden"})
    with pytest.raises(Exception):
        ch.send("ch1", "oi")


def test_mattermost_send_ok_does_not_raise():
    _wire(MattermostChannel("https://mm.example", "FAKE", "ch1", allow_all=True), {"id": "post1"}).send("ch1", "oi")
