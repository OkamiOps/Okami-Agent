"""Coalescing de entrada (paridade OpenClaw inbound-debounce): rajada de mensagens do MESMO chat no
mesmo lote de poll (paste partido, pensamento em 4 msgs) vira UM turno — antes cada msg era um turno
(lento e fora de ordem perceptual). Comando, mídia e chats diferentes NÃO se misturam."""

from __future__ import annotations

import tempfile

from okami.channels.base import Inbound
from okami.core import Task, TaskState
from okami.gateway import AgentEndpoint
from okami.gateway.coalesce import coalesce_inbound


def _t(chat, text, mid=""):
    return Inbound("fake", chat, text=text, msg_id=mid)


# ----------------------------------------------------------------- função pura
def test_merges_burst_from_same_chat():
    out = coalesce_inbound([_t("7", "oi"), _t("7", "esqueci de falar"), _t("7", "faz X")])
    assert len(out) == 1 and out[0].text == "oi\nesqueci de falar\nfaz X"


def test_keeps_msg_id_of_last():
    out = coalesce_inbound([_t("7", "a", mid="1"), _t("7", "b", mid="2")])
    assert out[0].msg_id == "2"


def test_different_chats_not_merged():
    out = coalesce_inbound([_t("7", "a"), _t("9", "b")])
    assert len(out) == 2


def test_commands_never_merge():
    out = coalesce_inbound([_t("7", "/stop"), _t("7", "e roda de novo")])
    assert len(out) == 2 and out[0].text == "/stop"


def test_media_messages_never_merge():
    img = Inbound("fake", "7", text="olha", image="/tmp/x.jpg")
    out = coalesce_inbound([_t("7", "primeiro"), img, _t("7", "depois")])
    assert len(out) == 3                                    # mídia quebra o agrupamento (ordem preservada)


def test_single_message_passthrough():
    out = coalesce_inbound([_t("7", "só uma")])
    assert len(out) == 1 and out[0].text == "só uma"


def test_order_preserved_across_chats():
    out = coalesce_inbound([_t("7", "a"), _t("9", "x"), _t("7", "b")])
    # 7: "a\nb" (na posição da primeira), 9: "x"
    assert [m.chat_id for m in out] == ["7", "9"] and out[0].text == "a\nb"


# ----------------------------------------------------------------- integração no endpoint
def test_poll_once_handles_burst_as_one_turn():
    goals: list[str] = []

    class Burst:
        name = "fake"
        def __init__(self):
            self._q = [[_t("7", "parte 1", "1"), _t("7", "parte 2", "2")]]
        def poll(self):
            return self._q.pop(0) if self._q else []
        def send(self, cid, text): pass
        def allowed(self, c): return True

    def runner(cfg, ws, goal, **kw):
        goals.append(goal)
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok"
        return t

    ep = AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=Burst(),
                       run_task=runner, spawn=lambda fn: fn())
    ep.poll_once()
    assert goals == ["parte 1\nparte 2"]                    # 1 turno, não 2


def test_poll_once_dedup_still_works():
    goals: list[str] = []

    class Redeliver:
        name = "fake"
        def __init__(self):
            self._q = [[_t("7", "oi", "1")], [_t("7", "oi", "1")]]   # mesma msg entregue 2x
        def poll(self):
            return self._q.pop(0) if self._q else []
        def send(self, cid, text): pass
        def allowed(self, c): return True

    def runner(cfg, ws, goal, **kw):
        goals.append(goal)
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok"
        return t

    ep = AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=Redeliver(),
                       run_task=runner, spawn=lambda fn: fn())
    ep.poll_once()
    ep.poll_once()
    assert goals == ["oi"]                                  # idempotência intacta
