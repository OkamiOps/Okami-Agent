"""/restart no chat + okami send (entrega sem LLM) — conveniências estilo Hermes.

Dor real: toda mudança termina em "reinicie o gateway", e do Telegram não dava — tinha
que ir ao terminal. Hermes tem /restart no chat (drena e o service manager relança) e
`hermes send` p/ scripts/cron mandarem mensagem SEM gastar token de LLM.
"""
from __future__ import annotations

import tempfile

from typer.testing import CliRunner

from okami.channels.base import Channel
from okami.cli import app
from okami.gateway import AgentEndpoint

runner = CliRunner()


class FakeChannel(Channel):
    name = "fake"

    def __init__(self):
        self.sent = []

    def poll(self):
        return []

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def allowed(self, chat_id):
        return True


def _ep():
    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=FakeChannel(),
                         run_task=lambda *a, **k: None, spawn=lambda fn: fn())


# ── /restart no chat ─────────────────────────────────────────────────────────

def test_restart_command_schedules_and_acks(monkeypatch):
    calls = []
    monkeypatch.setattr("okami.gateway.restart.schedule_self_restart",
                        lambda: calls.append(1) or (True, "reiniciando — volto em segundos."))
    ep = _ep()
    ep.handle("7", "/restart")
    assert calls == [1]
    assert any("reiniciando" in t for _, t in ep.channel.sent)


def test_restart_refused_outside_managed_background(monkeypatch):
    monkeypatch.setattr("okami.gateway.restart.schedule_self_restart",
                        lambda: (False, "gateway não está em background gerenciado."))
    ep = _ep()
    ep.handle("7", "/restart")
    assert any("não está em background" in t for _, t in ep.channel.sent)


def test_restart_listed_in_commands():
    from okami import commands as c
    assert any(d.name == "restart" for d in c.COMMAND_REGISTRY)


def test_schedule_self_restart_guard(tmp_path, monkeypatch):
    # pidfile com pid de OUTRO processo → recusa (evita 2º gateway disputando o polling)
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    (tmp_path / "runtime").mkdir(parents=True)
    (tmp_path / "runtime" / "gateway.pid").write_text("99999999")
    from okami.gateway.restart import schedule_self_restart
    ok, msg = schedule_self_restart()
    assert not ok


def test_schedule_self_restart_spawns_cli(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    (tmp_path / "runtime").mkdir(parents=True)
    (tmp_path / "runtime" / "gateway.pid").write_text(str(os.getpid()))   # somos o gateway gerenciado
    spawned = []
    monkeypatch.setattr("subprocess.Popen", lambda cmd, **k: spawned.append(cmd) or type("P", (), {"pid": 1})())
    from okami.gateway.restart import schedule_self_restart
    ok, msg = schedule_self_restart()
    assert ok, msg
    assert spawned and "restart" in spawned[0]            # delega pro CLI: para o velho e sobe o novo


# ── okami send (sem LLM) ─────────────────────────────────────────────────────

def _seed_agent(tmp_path, monkeypatch, chat="838", home_chat=""):
    import yaml
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    d = tmp_path / "minerva"
    d.mkdir(parents=True)
    spec = {"channels": {"telegram": {"token": "T0K", "allow_chats": [int(chat)]}}}
    (d / "agent.yaml").write_text(yaml.safe_dump(spec))
    if home_chat:
        hc = d / ".okami"
        hc.mkdir()
        (hc / "home_chat.txt").write_text(home_chat)
    return d


def test_send_to_explicit_chat(tmp_path, monkeypatch):
    _seed_agent(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr("okami.channels.telegram.TelegramChannel.send",
                        lambda self, cid, text: sent.append((self.client.token, str(cid), text)))
    res = runner.invoke(app, ["send", "backup concluído ✓", "--to", "telegram:838", "-a", "minerva"])
    assert res.exit_code == 0, res.output
    assert sent == [("T0K", "838", "backup concluído ✓")]


def test_send_defaults_to_home_chat(tmp_path, monkeypatch):
    _seed_agent(tmp_path, monkeypatch, home_chat="838")
    sent = []
    monkeypatch.setattr("okami.channels.telegram.TelegramChannel.send",
                        lambda self, cid, text: sent.append((str(cid), text)))
    res = runner.invoke(app, ["send", "lembrete", "-a", "minerva"])
    assert res.exit_code == 0, res.output
    assert sent == [("838", "lembrete")]


def test_send_without_target_fails_clean(tmp_path, monkeypatch):
    _seed_agent(tmp_path, monkeypatch)                      # sem home_chat
    res = runner.invoke(app, ["send", "oi", "-a", "minerva"])
    assert res.exit_code != 0
    assert "--to" in res.output or "sethome" in res.output  # explica como resolver


def test_send_agent_without_token_fails_clean(tmp_path, monkeypatch):
    import yaml
    monkeypatch.setattr("okami.home.agents_dir", lambda: tmp_path)
    d = tmp_path / "seco"
    d.mkdir()
    (d / "agent.yaml").write_text(yaml.safe_dump({}))
    res = runner.invoke(app, ["send", "oi", "--to", "telegram:1", "-a", "seco"])
    assert res.exit_code != 0
    assert "token" in res.output.lower()
