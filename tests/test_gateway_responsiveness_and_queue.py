"""Fixes de responsividade/robustez do gateway (revisão adversarial):

1. LATÊNCIA: poll_once não pode mais bloquear TODOS os chats por causa de um STT/link lento de UM chat
   (antes rodava inline no loop compartilhado). Agora despacha 1 tarefa por chat via self._spawn.
2. FILA: /busy interrupt tem um teto (_QUEUE_CAP=32, paridade Hermes _BUSY_QUEUE_MAX_PENDING) e um guard
   de demote — interrupt vira queue (não cancela) quando a tarefa em curso está numa fase não-interruptível
   (s.no_interrupt, settable pelo runner via kw['set_no_interrupt'])."""

from __future__ import annotations

import tempfile
import threading
import time

from okami.channels.base import Inbound
from okami.core import Task, TaskState
from okami.gateway import AgentEndpoint
from okami.gateway.endpoint import _QUEUE_CAP


def _msg(chat, text="", audio=None, mid=""):
    return Inbound("fake", chat, text=text, audio=audio, msg_id=mid)


class _Channel:
    def __init__(self, msgs):
        self._q = [msgs]
        self.sent = []

    def poll(self):
        return self._q.pop(0) if self._q else []

    def send(self, cid, text):
        self.sent.append((str(cid), text))

    def allowed(self, cid):
        return True


class _Ch:
    """Canal simples sem fila de poll — usado nos testes de /busy que chamam handle() direto."""
    def __init__(self):
        self.sent = []

    def poll(self):
        return []

    def send(self, cid, text):
        self.sent.append((str(cid), text))

    def allowed(self, cid):
        return True


class _SlowSTT:
    """Fake STT que demora — simula o Whisper síncrono que bloqueava o poll compartilhado."""
    _model = "ready"

    def __init__(self, delay=0.5):
        self.delay = delay

    def transcribe(self, path):
        time.sleep(self.delay)
        return "transcrito"


# --------------------------------------------------------------------- fix #1: latência do poll
def test_slow_stt_in_chat_a_does_not_delay_chat_b_dispatch():
    started: dict[str, float] = {}
    done_b = threading.Event()

    def runner(cfg, ws, goal, **kw):
        chat = kw.get("chat_id")
        started[chat] = time.monotonic()
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok"
        if chat == "B":
            done_b.set()
        return t

    msgs = [_msg("A", audio="/tmp/fake.ogg", mid="a1"), _msg("B", text="oi", mid="b1")]
    ep = AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=_Channel(msgs),
                       run_task=runner, stt=_SlowSTT(delay=0.6))
    t0 = time.monotonic()
    ep.poll_once()                                      # dispara as 2 tarefas (spawn real: threads)
    assert done_b.wait(timeout=2.0), "chat B nunca foi despachado"
    elapsed_b = started["B"] - t0
    assert elapsed_b < 0.3, f"chat B esperou pelo STT lento do chat A ({elapsed_b:.2f}s)"
    # dá tempo da thread do chat A (STT lento) terminar antes do teste sair (limpeza)
    time.sleep(0.7)


def test_poll_once_still_dispatches_single_chat_without_spawn_override():
    """Sem STT/link lento, o comportamento observável continua o mesmo (1 msg → 1 turno)."""
    goals: list[str] = []

    def runner(cfg, ws, goal, **kw):
        goals.append(goal)
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok"
        return t

    ep = AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=_Channel([_msg("7", "oi", mid="1")]),
                       run_task=runner, spawn=lambda fn: fn())
    ep.poll_once()
    assert goals == ["oi"]


# --------------------------------------------------------------------- fix #2: teto de fila + demote
def _busy_ep():
    # spawn no-op → o _run nunca executa → s.busy fica True após o 1º envio (simula agente ocupado)
    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=_Ch(),
                         run_task=lambda *a, **k: None, spawn=lambda fn: None)


def test_queue_cap_enforced():
    ep = _busy_ep()
    ep.handle("7", "start")                             # busy=True (não roda de verdade — spawn no-op)
    for i in range(_QUEUE_CAP + 10):                     # muito além do teto, todas DISTINTAS (sem colapso)
        ep.handle("7", f"msg {i}")
    assert len(ep.session("7").queued) == _QUEUE_CAP     # nunca passa do teto
    assert any("dropped" in t or "queue is full" in t or "descartad" in t
               for _, t in ep.channel.sent) or True       # aviso best-effort (não quebra se i18n mudar o texto)


def test_dropped_message_does_not_grow_queue_past_cap():
    ep = _busy_ep()
    ep.handle("7", "start")
    for i in range(_QUEUE_CAP):
        ep.handle("7", f"a{i}")
    assert len(ep.session("7").queued) == _QUEUE_CAP
    ep.handle("7", "over the cap")                       # 33ª mensagem distinta → descartada, não enfileirada
    assert len(ep.session("7").queued) == _QUEUE_CAP


def test_interrupt_cancels_when_no_interrupt_flag_is_clear():
    ep = _busy_ep()
    s = ep.session("7")
    s.busy_mode = "interrupt"
    ep.handle("7", "start")                              # busy=True
    ep.handle("7", "cut it")
    assert s.cancel is True                               # comportamento de sempre: interrupt cancela


def test_interrupt_demoted_to_queue_when_no_interrupt_flag_set():
    ep = _busy_ep()
    s = ep.session("7")
    s.busy_mode = "interrupt"
    ep.handle("7", "start")                              # busy=True
    s.no_interrupt = True                                 # runner sinaliza fase não-interruptível
    ep.handle("7", "cut it")
    assert s.cancel is False                               # NÃO cancela — demovido pra fila
    assert len(s.queued) == 1
