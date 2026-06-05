"""Base p/ canais REST-polling (Slack/Discord/Mattermost) — mesma interface Channel do Telegram.

`request_json` (urllib, sem dep extra) + `RestChannel` com `_get`/`_post` MOCKÁVEIS (teste sem rede) e
allowed() DENY-BY-DEFAULT (o canal CONFIGURADO é o opt-in; qualquer outro precisa de allow/allow_all).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from okami.channels.base import Channel


def request_json(method: str, url: str, *, headers=None, params=None, body=None, timeout: float = 30) -> dict:
    if params:
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        if q:
            url += ("&" if "?" in url else "?") + q
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        raw = r.read().decode("utf-8", "ignore")
    return json.loads(raw) if raw.strip() else {}


class RestChannel(Channel):
    base_url = ""
    poll_interval = 3.0       # REST não long-polla → o loop do gateway espera isto entre polls (anti-spin)

    def __init__(self, channel_id, *, allow_chats=None, allow_all: bool = False):
        self.channel_id = str(channel_id)
        self.allow = {str(c) for c in (allow_chats or [])}
        self.allow_all = bool(allow_all)

    @property
    def headers(self) -> dict:               # sobrescrito por cada canal (auth)
        return {}

    def _get(self, path: str, params=None) -> dict:
        return request_json("GET", self.base_url + path, headers=self.headers, params=params)

    def _post(self, path: str, body) -> dict:
        return request_json("POST", self.base_url + path, headers=self.headers, body=body)

    def allowed(self, chat_id) -> bool:
        if str(chat_id) == self.channel_id:  # o canal CONFIGURADO É o opt-in explícito
            return True
        if self.allow:
            return str(chat_id) in self.allow
        return self.allow_all                # deny-by-default (igual ao Telegram)
