"""Paridade Hermes (_is_fresh_gateway_interruption): no boot, só auto-resume tarefa interrompida se ela for
RECENTE (janela default 1h). Sem isso, uma VPS que reinicia 2 dias depois ressuscitava um turno morto com
contexto/tool-tail velho. Velho/sem-timestamp → NÃO resume; avisa e oferece /retry."""
from __future__ import annotations

import time

from okami.gateway.endpoint import AgentEndpoint, Session


def _ep(last_ts):
    ep = AgentEndpoint.__new__(AgentEndpoint)
    s = Session()
    s.history = [("USER", "faça X")]                  # interrompido: termina em USER sem resposta
    ep.auto_resume = True
    ep.resume_freshness = 3600.0
    spawned, sent = [], []
    ep._all_session_ids = lambda: ["c1"]
    ep.session = lambda cid: s

    class _Store:
        def entry(self, cid): return {"last_interaction_at": last_ts}
    ep.store = _Store()

    class _Ch:
        def send(self, cid, text): sent.append(text)
    ep.channel = _Ch()
    ep._spawn = lambda fn: spawned.append(fn)
    ep._save_meta = lambda cid, ss: None
    ep._run = lambda *a, **k: None
    return ep, spawned, sent


def test_fresh_interruption_auto_resumes():
    ep, spawned, sent = _ep(time.time() - 60)         # 1 min atrás → fresco
    ep.resume_interrupted(auto_resume=True)
    assert spawned                                     # re-executou


def test_stale_interruption_notifies_instead_of_resuming():
    ep, spawned, sent = _ep(time.time() - 7200)        # 2h atrás → velho (> janela 1h)
    ep.resume_interrupted(auto_resume=True)
    assert not spawned                                 # NÃO ressuscitou o turno morto
    assert any("/retry" in t for t in sent)            # avisou + ofereceu /retry


def test_missing_timestamp_does_not_auto_resume():
    ep, spawned, sent = _ep(0)                          # sem timestamp → idade desconhecida → seguro
    ep.resume_interrupted(auto_resume=True)
    assert not spawned
