"""Paridade Hermes (busy queue collapse repeated sends): se o dono RE-ENVIA a MESMA mensagem enquanto o
agente está ocupado (double-tap / reenvio por ansiedade), o Okami enfileirava N cópias e rodava a tarefa N
vezes. Agora colapsa a repetição contra o último slot da fila → roda 1x. Mensagens DISTINTAS seguem FIFO."""
from __future__ import annotations

import tempfile

from okami.gateway import AgentEndpoint


class _Ch:
    def __init__(self): self.sent = []
    def poll(self): return []
    def send(self, cid, text): self.sent.append((str(cid), text))
    def allowed(self, cid): return True


def _busy_ep():
    # spawn no-op → o _run nunca executa → s.busy fica True após o 1º envio (simula agente ocupado)
    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=_Ch(),
                         run_task=lambda *a, **k: None, spawn=lambda fn: None)


def test_repeated_send_while_busy_collapses_to_one():
    ep = _busy_ep()
    ep.handle("7", "faz X")                       # start → busy
    ep.handle("7", "faz X")                       # repetida → colapsa
    ep.handle("7", "faz X")                       # repetida → colapsa
    assert len(ep.session("7").queued) == 1       # 3 iguais → 1 na fila (não roda 3x)


def test_distinct_messages_while_busy_keep_fifo():
    ep = _busy_ep()
    ep.handle("7", "faz X")                       # start → busy
    ep.handle("7", "faz Y")                       # distinta → fila
    ep.handle("7", "faz Z")                       # distinta → fila
    assert len(ep.session("7").queued) == 2       # Y, Z preservadas (distintas)
