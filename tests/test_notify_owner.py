"""Notificação ao dono fora-do-turno (pesquisa #7 item 3) — o harness avisa o dono via closure `notify`.

A tarefa de longa duração (vigia/loop) precisa "tocar" o dono sem esperar o fim do turno. O gateway
expõe `notify(msg)` no kw do run_task; ela entrega ao home_chat (ou ao chat atual), redige segredo, e
opcionalmente dispara notificação desktop (item 4) quando a flag de config estiver ligada.
"""
from __future__ import annotations

import tempfile

from okami.channels.base import Channel
from okami.core import Task, TaskState
from okami.gateway import AgentEndpoint


class FakeChannel(Channel):
    name = "fake"

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def poll(self):
        return []

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def allowed(self, chat_id):
        return True


def _ep(runner, cfg=None):
    ch = FakeChannel()
    return AgentEndpoint("dev", cfg=cfg, ws=tempfile.mkdtemp(), channel=ch, run_task=runner,
                         approval_mode="manual", spawn=lambda fn: fn())


def test_notify_closure_in_kw_delivers_to_home_chat():
    captured = {}

    def _runner(cfg, ws, goal, *, notify=None, **kw):
        captured["notify"] = notify
        if notify:
            captured["ret"] = notify("vigia: o deploy terminou")
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok"
        return t

    ep = _ep(_runner)
    ep.set_home("999")                                  # home_chat definido → notify entrega lá
    ep.handle("7", "fica de olho no deploy")
    assert callable(captured["notify"])                 # o kw realmente carrega a closure
    assert captured["ret"] is True                      # _notify_owner devolve True ao entregar
    # entregue ao home_chat (999), não ao chat de origem (7), com prefixo [notify]
    assert any(cid == "999" and "[notify]" in t and "o deploy terminou" in t
               for cid, t in ep.channel.sent)


def test_notify_falls_back_to_chat_when_no_home():
    def _runner(cfg, ws, goal, *, notify=None, **kw):
        if notify:
            notify("aviso do meio do caminho")
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok"
        return t

    ep = _ep(_runner)                                   # sem set_home → cai no chat de origem
    ep.handle("42", "roda")
    assert any(cid == "42" and "[notify]" in t and "aviso do meio do caminho" in t
               for cid, t in ep.channel.sent)


def test_notify_redacts_secret():
    def _runner(cfg, ws, goal, *, notify=None, **kw):
        if notify:
            notify("token vazou: sk-ABCDEF0123456789abcdef0123456789 cuidado")
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok"
        return t

    ep = _ep(_runner)
    ep.handle("7", "roda")
    body = "\n".join(t for _, t in ep.channel.sent)
    assert "sk-ABCDEF0123456789abcdef0123456789" not in body   # notify redige antes de enviar
    assert "«redacted»" in body


def test_notify_owner_direct_returns_bool():
    """_notify_owner é chamável direto (closure só embrulha) e devolve True quando entrega."""
    ep = _ep(_runner_noop())
    ok = ep._notify_owner("7", "mensagem solta")
    assert ok is True
    assert any("[notify]" in t and "mensagem solta" in t for _, t in ep.channel.sent)


def test_notify_desktop_flag_triggers_desktop(monkeypatch):
    """Com a flag notifications.desktop ligada, _notify_owner também chama desktop_notify (best-effort)."""
    calls = []

    class _Cfg:
        notifications = {"desktop": True}

    def _fake_desktop(title, body):
        calls.append((title, body))
        return True

    import okami.core.desktop as desk
    monkeypatch.setattr(desk, "desktop_notify", _fake_desktop)
    ep = _ep(_runner_noop(), cfg=_Cfg())
    ep._notify_owner("7", "terminou a build")
    assert calls and calls[0][0] == "Okami" and "terminou a build" in calls[0][1]


def test_notify_desktop_off_by_default(monkeypatch):
    """Sem a flag, NÃO chama desktop (silencioso por padrão)."""
    calls = []
    import okami.core.desktop as desk
    monkeypatch.setattr(desk, "desktop_notify", lambda t, b: calls.append((t, b)))
    ep = _ep(_runner_noop(), cfg=None)                  # cfg None → flag ausente
    ep._notify_owner("7", "build")
    assert calls == []


def _runner_noop():
    def _r(cfg, ws, goal, *, notify=None, **kw):
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok"
        return t
    return _r
