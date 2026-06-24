"""Paridade Hermes (agent cache LRU): self.sessions crescia SEM LIMITE — vazamento de memória numa VPS 24/7
servindo muitos chats. Agora tem teto: as sessões IDLE mais antigas são despejadas além do cap (reconstroem
do transcript no próximo acesso → seguro). Sessão BUSY NUNCA é despejada (tem estado vivo: busy/queued)."""
from __future__ import annotations

import tempfile

from okami.gateway import AgentEndpoint


class _Ch:
    def poll(self): return []
    def send(self, cid, text): pass
    def allowed(self, cid): return True


def _ep():
    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=_Ch(),
                         run_task=lambda *a, **k: None, spawn=lambda fn: None)


def test_idle_sessions_evicted_beyond_cap():
    ep = _ep()
    ep.max_live_sessions = 3
    for i in range(6):
        ep.session(f"c{i}")                        # 6 sessões idle distintas, cap 3
    assert len(ep.sessions) <= 3                    # as 3 mais antigas saíram (memória limitada)


def test_busy_session_never_evicted():
    ep = _ep()
    ep.max_live_sessions = 2
    s0 = ep.session("c0")
    s0.busy = True                                 # ocupada → protegida
    for i in range(1, 8):
        ep.session(f"c{i}")
    assert "c0" in ep.sessions                      # nunca despejada (estado vivo)
