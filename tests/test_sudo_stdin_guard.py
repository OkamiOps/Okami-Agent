"""sudo -S stdin guard (pesquisa #6 item 16, paridade Hermes approval _check_sudo_stdin_guard).

`sudo -S` lê a senha do STDIN — um LLM que escreve `-S` está CHUTANDO senha (ou esperando que o
harness injete uma). Bloqueio INCONDICIONAL quando SUDO_PASSWORD não está no ambiente — roda antes
do yolo (nem yolo passa), junto do hardline floor. Com SUDO_PASSWORD setado (uso deliberado do dono),
passa pro gate de aprovação normal.
"""
from __future__ import annotations

from okami.core.approval import detect_hardline, sudo_stdin_blocked


def test_sudo_dash_s_blocked_without_password(monkeypatch):
    monkeypatch.delenv("SUDO_PASSWORD", raising=False)
    assert sudo_stdin_blocked("sudo -S apt install x") is not None
    assert sudo_stdin_blocked("echo hunter2 | sudo -S rm /etc/hosts") is not None
    assert sudo_stdin_blocked("sudo --stdin reboot") is not None


def test_sudo_dash_s_allowed_with_password_env(monkeypatch):
    monkeypatch.setenv("SUDO_PASSWORD", "x")
    assert sudo_stdin_blocked("sudo -S apt install x") is None   # dono habilitou deliberadamente


def test_plain_sudo_not_stdin_blocked(monkeypatch):
    monkeypatch.delenv("SUDO_PASSWORD", raising=False)
    assert sudo_stdin_blocked("sudo apt install x") is None      # sudo normal → gate de aprovação, não bloqueio
    assert sudo_stdin_blocked("ls -S") is None                   # -S de OUTRO comando (sort by size) não casa


def test_sudo_stdin_is_hardline_level(monkeypatch):
    # entra no detect_hardline → bloqueio incondicional no run_shell (mesma porta do rm -rf /)
    monkeypatch.delenv("SUDO_PASSWORD", raising=False)
    assert detect_hardline("sudo -S systemctl stop firewall") is not None


def test_sudo_stdin_runs_before_yolo(tmp_path, monkeypatch):
    # mesmo em yolo, run_shell bloqueia sudo -S (hardline é incondicional)
    monkeypatch.delenv("SUDO_PASSWORD", raising=False)
    from okami.core.tools import ToolContext
    from okami.core.tools.files import RunShell
    from okami.core.sandbox import SandboxPolicy
    ctx = ToolContext(workspace=tmp_path, sandbox=SandboxPolicy(mode="yolo"))
    res = RunShell().run({"cmd": "sudo -S whoami"}, ctx)
    assert not res.ok and ("BLOQUEADO" in res.output or "hardline" in res.output.lower())
