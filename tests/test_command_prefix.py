"""Paridade Hermes (typed_command_prefix): canal que intercepta '/' (Slack/Matrix) declara command_prefix='!';
o gateway normaliza p/ '/' ANTES do pipeline de comando → '!help' funciona igual '/help'. Default '/' intacto."""
from __future__ import annotations

import tempfile

from okami.gateway import AgentEndpoint


class _Ch:
    command_prefix = "!"
    def poll(self): return []
    def send(self, cid, text): self.sent.append(str(text))
    def allowed(self, cid): return True
    def __init__(self): self.sent = []


class _Slash(_Ch):
    command_prefix = "/"


def _ep(ch):
    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=ch,
                         run_task=lambda *a, **k: None, spawn=lambda fn: fn())


def test_bang_prefix_normalized_to_slash():
    ch = _Ch()
    _ep(ch).handle("7", "!help")
    assert any("/" in t for t in ch.sent) and ch.sent          # help respondeu (não virou mensagem pro modelo)


def test_bang_channel_plain_text_unaffected():
    ch = _Ch()
    ep = _ep(ch)
    ep.handle("7", "oi tudo bem")                              # texto normal não começa com '!' → intacto
    # não deve ter sido tratado como comando desconhecido
    assert not any("unknown command" in t.lower() or "comando" in t.lower() for t in ch.sent)


def test_default_slash_channel_still_works():
    ch = _Slash()
    _ep(ch).handle("7", "/help")
    assert ch.sent                                             # '/help' continua funcionando
