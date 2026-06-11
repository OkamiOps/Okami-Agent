"""Ciclo de vida do gateway por SUBCOMANDO: okami gateway start|stop|status|restart.

Dor real: depois de cada mudança eu mandava o Marcos "reiniciar o gateway" e o comando
não existia — só as flags --stop/--status (e nada de restart). Hermes expõe lifecycle
como ação nomeada; aqui o argumento posicional faz o mesmo, mantendo as flags antigas.
"""
from __future__ import annotations

from typer.testing import CliRunner

from okami.cli import app

runner = CliRunner()


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)


def test_status_when_stopped(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    res = runner.invoke(app, ["gateway", "status"])
    assert res.exit_code == 0
    assert "parado" in res.output


def test_stop_when_not_running_is_clean(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    res = runner.invoke(app, ["gateway", "stop"])
    assert res.exit_code == 0
    assert "não está rodando" in res.output


def test_restart_stops_old_and_starts_new(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    (tmp_path / "runtime").mkdir(parents=True)
    (tmp_path / "runtime" / "gateway.pid").write_text("4242")

    killed = []
    monkeypatch.setattr("okami.cli.commands.gateway._pid_alive",
                        lambda pid: pid == 4242 and not killed)   # vivo até ser morto
    monkeypatch.setattr("os.kill", lambda pid, sig: killed.append(pid))

    started = []

    class _Proc:
        pid = 5555

    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: started.append(a) or _Proc())
    monkeypatch.setattr("okami.agents.load_agents", lambda root=None: {"okami": object()})

    res = runner.invoke(app, ["gateway", "restart"])
    assert res.exit_code == 0, res.output
    assert killed == [4242]                                       # parou o antigo
    assert started                                                # subiu o novo
    assert (tmp_path / "runtime" / "gateway.pid").read_text() == "5555"


def test_restart_when_stopped_just_starts(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    class _Proc:
        pid = 5555

    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: _Proc())
    monkeypatch.setattr("okami.agents.load_agents", lambda root=None: {"okami": object()})
    res = runner.invoke(app, ["gateway", "restart"])
    assert res.exit_code == 0, res.output
    assert (tmp_path / "runtime" / "gateway.pid").read_text() == "5555"


def test_legacy_flags_still_work(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    res = runner.invoke(app, ["gateway", "--status"])
    assert res.exit_code == 0 and "parado" in res.output


def test_unknown_action_rejected(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    res = runner.invoke(app, ["gateway", "banana"])
    assert res.exit_code != 0
    assert "restart" in res.output.lower()                        # mostra as ações válidas
