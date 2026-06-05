"""CLI de supervisão de processos (okami ps / process log|kill|signal|wait) — sobre o ProcessManager."""

from __future__ import annotations

from typer.testing import CliRunner

from okami.cli import app
from okami.core.processes import ProcessManager

runner = CliRunner()


def test_process_list_log_and_ps_shortcut(tmp_path):
    pm = ProcessManager(tmp_path)
    meta = pm.start("echo hello-from-proc; sleep 0.2")
    pid = meta["id"]
    pm.wait(pid, timeout=5)                                   # deixa terminar
    out = runner.invoke(app, ["process", "list", "-w", str(tmp_path)]).output
    assert pid in out and "exited" in out
    log = runner.invoke(app, ["process", "log", pid, "-w", str(tmp_path)]).output
    assert "hello-from-proc" in log
    assert pid in runner.invoke(app, ["ps", "-w", str(tmp_path)]).output   # atalho ps == list


def test_process_kill_and_unknown(tmp_path):
    pm = ProcessManager(tmp_path)
    pid = pm.start("sleep 30")["id"]
    assert runner.invoke(app, ["process", "kill", pid, "-w", str(tmp_path)]).exit_code == 0
    assert pm.poll(pid)["status"] == "exited"                # morto de verdade
    assert runner.invoke(app, ["process", "kill", "naoexiste", "-w", str(tmp_path)]).exit_code == 1


def test_process_wait_and_clean(tmp_path):
    pm = ProcessManager(tmp_path)
    pid = pm.start("echo ok")["id"]
    w = runner.invoke(app, ["process", "wait", pid, "-w", str(tmp_path)])
    assert w.exit_code == 0 and "terminou" in w.output
    # clean --dry-run não apaga (ttl 0 → tudo já terminado é candidato)
    out = runner.invoke(app, ["process", "clean", "-w", str(tmp_path), "--ttl-hours", "0", "--dry-run"]).output
    assert "seriam removidos" in out and pm.poll(pid)["status"] == "exited"


def test_process_list_empty(tmp_path):
    out = runner.invoke(app, ["process", "list", "-w", str(tmp_path)]).output
    assert "nenhum processo" in out
