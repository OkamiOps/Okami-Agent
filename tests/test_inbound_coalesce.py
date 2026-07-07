"""Coalescing de entrada (paridade OpenClaw inbound-debounce): rajada de mensagens do MESMO chat no
mesmo lote de poll (paste partido, pensamento em 4 msgs) vira UM turno — antes cada msg era um turno
(lento e fora de ordem perceptual). Comando, mídia e chats diferentes NÃO se misturam."""

from __future__ import annotations

import tempfile

from okami.channels.base import Inbound
from okami.core import Task, TaskState
from okami.gateway import AgentEndpoint
from okami.gateway.coalesce import WindowCoalescer, coalesce_inbound


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


# ----------------------------------------------------------------- fix #3: debounce por janela (cross-poll)
def test_window_coalescer_merges_across_polls_within_window():
    wc = WindowCoalescer(window=3.0)
    out1 = wc.feed([_t("7", "primeira parte")], now=0.0)
    assert out1 == []                                       # segurado — pode vir mais coisa
    out2 = wc.feed([_t("7", "segunda parte")], now=1.0)      # chegou 1s depois (dentro da janela)
    assert out2 == []                                        # ainda segurado, relógio reiniciado
    out3 = wc.feed([], now=1.0 + 3.1)                        # 3.1s sem novidade → libera
    assert len(out3) == 1 and out3[0].text == "primeira parte\nsegunda parte"


def test_window_coalescer_releases_after_window_with_no_more_messages():
    wc = WindowCoalescer(window=3.0)
    wc.feed([_t("7", "oi")], now=0.0)
    out = wc.feed([], now=3.5)
    assert len(out) == 1 and out[0].text == "oi"


def test_window_coalescer_flushes_on_nonmergeable_message():
    wc = WindowCoalescer(window=3.0)
    wc.feed([_t("7", "oi")], now=0.0)
    cmd = Inbound("fake", "7", text="/stop")
    out = wc.feed([cmd], now=0.5)                             # comando fecha o grupo aberto na hora
    assert [m.text for m in out] == ["oi", "/stop"]


def test_window_coalescer_different_chats_independent():
    wc = WindowCoalescer(window=3.0)
    wc.feed([_t("7", "a")], now=0.0)
    wc.feed([_t("9", "x")], now=0.5)
    out = wc.feed([], now=10.0)                               # os dois esfriaram, cada um vira 1 msg
    assert sorted(m.chat_id for m in out) == ["7", "9"]


def test_window_coalescer_disabled_when_window_zero():
    wc = WindowCoalescer(window=0)
    out1 = wc.feed([_t("7", "a")], now=0.0)
    assert len(out1) == 1                                     # opt-out: não segura nada, sai na hora
    out2 = wc.feed([_t("7", "b")], now=0.1)
    assert len(out2) == 1 and out2[0].text == "b"              # sem merge (window desligada)


def test_endpoint_default_coalesce_window_is_disabled():
    """Default é opt-in DESLIGADO: sem config explícita, poll_once não segura mensagem nenhuma
    (comportamento igual ao coalesce_inbound por-lote puro — sem latência extra pro caso comum)."""
    ep = AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=_ChStub([]),
                       run_task=lambda *a, **k: None, spawn=lambda fn: fn())
    assert ep._coalescer.window == 0


class _ChStub:
    def __init__(self, msgs):
        self._msgs = msgs
    def poll(self):
        return []
    def send(self, cid, text):
        pass
    def allowed(self, c):
        return True
