"""Onda 2: parada GRACIOSA do gateway (SIGTERM/restart não mata no meio) + dedup de mensagens sobrevive
ao restart (não reprocessa msg já vista). Importa pra um agente 24/7 que se reinicia sozinho."""
from __future__ import annotations

from okami.channels.base import Channel
from okami.gateway import AgentEndpoint


class _Ch(Channel):
    name = "fake"

    def poll(self):
        return []

    def send(self, chat_id, text):
        pass

    def allowed(self, chat_id):
        return True


def _ep(ws):
    return AgentEndpoint("dev", None, str(ws), _Ch(), run_task=lambda *a, **k: None, spawn=lambda fn: fn())


def test_request_stop_drains_and_persists(tmp_path):
    ep = _ep(tmp_path)
    ep._seen_msgs["m1"] = True
    assert ep.running is True
    ep.request_stop("test")
    assert ep.running is False                          # loop sai após a iteração atual
    assert ep._seen_path().is_file()                    # dedup gravado no shutdown


def test_seen_dedup_survives_restart(tmp_path):
    ep1 = _ep(tmp_path)
    ep1._seen_msgs["abc"] = True
    ep1._seen_msgs["def"] = True
    ep1._persist_seen()
    ep2 = _ep(tmp_path)                                 # "reinício"
    assert "abc" not in ep2._seen_msgs                  # começa limpo…
    ep2._load_seen()
    assert "abc" in ep2._seen_msgs and "def" in ep2._seen_msgs   # …e recupera o que já tinha visto
