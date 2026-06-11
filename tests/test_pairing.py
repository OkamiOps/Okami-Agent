"""Pareamento dinâmico (paridade Hermes): chat não-autorizado recebe um CÓDIGO; o dono aprova pelo
CLI (`okami pair approve <code>`) e o chat entra no allowlist PERSISTENTE — sem editar agent.yaml na
mão nem reiniciar o gateway. Resolve a dor 'bot fica MUDO até configurar allow_chats'."""

from __future__ import annotations

import tempfile
from pathlib import Path

from typer.testing import CliRunner

from okami.channels.base import Channel
from okami.core import Task, TaskState
from okami.gateway import AgentEndpoint
from okami.gateway.pairing import PairingStore

runner = CliRunner()


# ----------------------------------------------------------------- PairingStore (unidade)
def test_request_code_returns_code_and_persists_pending(tmp_path):
    s = PairingStore(tmp_path)
    code = s.request_code("123", now=1000.0)
    assert code and not s.is_approved("123")
    assert any(p["chat_id"] == "123" and p["code"] == code for p in s.pending(now=1000.0))


def test_request_code_dedups_per_chat(tmp_path):
    s = PairingStore(tmp_path)
    c1 = s.request_code("123", now=1000.0)
    c2 = s.request_code("123", now=1001.0)               # mesmo chat → MESMO código (não spamma)
    assert c1 == c2 and len(s.pending(now=1001.0)) == 1


def test_approve_moves_pending_to_approved(tmp_path):
    s = PairingStore(tmp_path)
    code = s.request_code("123", now=1000.0)
    assert s.approve(code, now=1000.0) == "123"
    assert s.is_approved("123") and not s.pending(now=1000.0)


def test_approve_bad_code_returns_none(tmp_path):
    assert PairingStore(tmp_path).approve("ZZZZ", now=1000.0) is None


def test_request_code_empty_for_already_approved(tmp_path):
    s = PairingStore(tmp_path)
    s.approve_chat("123")
    assert s.request_code("123", now=1000.0) == ""        # já aprovado → não precisa de código


def test_pending_expires_after_ttl(tmp_path):
    s = PairingStore(tmp_path)
    code = s.request_code("123", now=1000.0, ttl=3600)
    assert not s.pending(now=1000.0 + 3601)               # expirou
    assert s.approve(code, now=1000.0 + 3601) is None     # código velho não aprova


def test_revoke_removes_approval(tmp_path):
    s = PairingStore(tmp_path)
    s.approve_chat("123")
    assert s.revoke("123") and not s.is_approved("123")


def test_persists_across_instances(tmp_path):
    PairingStore(tmp_path).approve_chat("123")
    assert PairingStore(tmp_path).is_approved("123")      # outro processo (CLI) vê o que o gateway gravou


def test_pairing_file_is_private(tmp_path):
    s = PairingStore(tmp_path)
    s.approve_chat("123")
    mode = (Path(tmp_path) / ".okami" / "pairing.json").stat().st_mode & 0o777
    assert mode == 0o600                                  # contém ids de usuário → 0600


# ----------------------------------------------------------------- endpoint: gate + emissão do código
class Cap(Channel):
    name = "telegram"                                     # superfície remota (deny-by-default)

    def __init__(self, allow_chats=None):
        self.sent: list[tuple[str, str]] = []
        self.allow = {str(c) for c in (allow_chats or [])}

    def poll(self):
        return []

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def allowed(self, chat_id):
        return str(chat_id) in self.allow                 # só o allowlist estático do canal


def _ep(ch, ran):
    def runner_fn(cfg, ws, goal, **kw):
        ran.append(goal)
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "feito"
        return t

    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=ch,
                         run_task=runner_fn, spawn=lambda fn: fn())


def test_unauthorized_chat_gets_pairing_code_not_bare_refusal():
    ran: list = []
    ep = _ep(Cap(), ran)
    ep.handle("999", "oi")
    assert not ran                                        # tarefa NÃO rodou
    msgs = " ".join(t for _, t in ep.channel.sent)
    pend = ep._pairing.pending()
    assert pend and pend[0]["code"] in msgs               # o código foi entregue ao usuário
    assert "okami pair" in msgs.lower()                   # instrução de aprovação pelo dono


def test_approved_via_pairing_runs_the_task():
    ran: list = []
    ep = _ep(Cap(), ran)
    ep.handle("999", "oi")                                # gera pendência
    code = ep._pairing.pending()[0]["code"]
    ep._pairing.approve(code)
    ep.handle("999", "agora roda")
    assert "agora roda" in ran                            # aprovado → executa


def test_channel_allowlisted_chat_skips_pairing():
    ran: list = []
    ep = _ep(Cap(allow_chats=["55"]), ran)
    ep.handle("55", "manda ver")
    assert "manda ver" in ran and not ep._pairing.pending()


# ----------------------------------------------------------------- CLI: okami pair
def test_cli_pair_list_and_approve(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.cli._shared._persona_ws", lambda agent, workspace: tmp_path)
    s = PairingStore(tmp_path)
    code = s.request_code("777")                         # tempo real → não expira no `list` do CLI
    out = runner.invoke(app_pair := __import__("okami.cli", fromlist=["app"]).app,
                        ["pair", "list", "-w", str(tmp_path)])
    assert out.exit_code == 0 and code in out.output and "777" in out.output
    res = runner.invoke(app_pair, ["pair", "approve", code, "-w", str(tmp_path)])
    assert res.exit_code == 0
    assert PairingStore(tmp_path).is_approved("777")


def test_cli_pair_add_and_revoke(tmp_path, monkeypatch):
    from okami.cli import app
    monkeypatch.setattr("okami.cli._shared._persona_ws", lambda agent, workspace: tmp_path)
    assert runner.invoke(app, ["pair", "add", "42", "-w", str(tmp_path)]).exit_code == 0
    assert PairingStore(tmp_path).is_approved("42")
    assert runner.invoke(app, ["pair", "revoke", "42", "-w", str(tmp_path)]).exit_code == 0
    assert not PairingStore(tmp_path).is_approved("42")
