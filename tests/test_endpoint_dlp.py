"""DLP de saída (pesquisa #7 item 2) — a resposta do agente é REDIGIDA antes de sair pelo canal.

Mesmo que o modelo cuspa um segredo (sk-…, OPENAI_API_KEY=…) na resposta final, o gateway mascara
ANTES de `channel.send` — tanto no caminho feliz quanto no caminho de erro. Texto normal passa intacto.
"""
from __future__ import annotations

import tempfile

from okami.channels.base import Channel
from okami.core import Task, TaskState
from okami.gateway import AgentEndpoint


class FakeChannel(Channel):
    name = "fake"

    def __init__(self, allow_chats=None):
        self.sent: list[tuple[str, str]] = []
        self.allow = {str(c) for c in (allow_chats or [])}

    def poll(self):
        return []

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def allowed(self, chat_id):
        return not self.allow or str(chat_id) in self.allow


def _ep(runner):
    ch = FakeChannel()
    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=ch, run_task=runner,
                         approval_mode="manual", spawn=lambda fn: fn())


def _runner_returning(reply):
    def _r(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, **kw):
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, reply
        return t
    return _r


def test_reply_with_openai_key_is_redacted_before_send():
    secret = "sk-ABCDEF0123456789abcdef0123456789"
    ep = _ep(_runner_returning(f"a chave é {secret} pronto"))
    ep.handle("7", "qual a chave?")
    body = "\n".join(t for _, t in ep.channel.sent)
    assert secret not in body                          # o segredo NÃO vazou pro canal
    assert "«redacted»" in body                        # foi mascarado pelo redator central


def test_reply_with_env_assignment_is_redacted():
    ep = _ep(_runner_returning("config: OPENAI_API_KEY=tok_supersecreto_xyz feito"))
    ep.handle("7", "mostra a config")
    body = "\n".join(t for _, t in ep.channel.sent)
    assert "tok_supersecreto_xyz" not in body
    assert "«redacted»" in body


def test_normal_reply_is_unchanged():
    ep = _ep(_runner_returning("o relatório está pronto, são 3 itens"))
    ep.handle("7", "e aí?")
    body = "\n".join(t for _, t in ep.channel.sent)
    assert "o relatório está pronto, são 3 itens" in body   # texto comum passa intacto


def test_error_path_reply_is_redacted():
    secret = "sk-DEADBEEF0123456789cafebabe012345"

    def _boom(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, **kw):
        raise RuntimeError(f"falhou com a chave {secret}")   # erro carrega segredo

    ep = _ep(_boom)
    ep.handle("7", "roda isso")
    body = "\n".join(t for _, t in ep.channel.sent)
    assert secret not in body                          # caminho de erro também redige
    assert any("❌" in t for _, t in ep.channel.sent)   # ainda avisa o erro
