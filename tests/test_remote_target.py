"""RemoteTarget — monta o comando ssh/tailscale e roda via subprocess injetável (sem rede no teste).

Núcleo do ambiente remoto: o agente "entra" num host e seus comandos rodam LÁ. Aqui cobrimos o
build do argv (tailscale primário + ssh fallback com ControlMaster), o cwd, e o run() com runner
mockado — incluindo o opt-in de SSH_AUTH_SOCK só no caminho ssh.
"""
from __future__ import annotations

from okami.integrations.remote import RemoteTarget


def test_build_argv_tailscale_sem_cwd():
    rt = RemoteTarget(alias="prod", host="prod-server", via="tailscale")
    argv = rt.build_argv("ls -la")
    assert argv[:3] == ["tailscale", "ssh", "prod-server"]
    assert argv[-3:] == ["bash", "-lc", "ls -la"]        # comando vai como UM arg p/ bash -lc (sem shell=True)


def test_build_argv_ssh_tem_controlmaster():
    rt = RemoteTarget(alias="nas", host="deploy@10.0.0.5", via="ssh")
    argv = rt.build_argv("uptime")
    assert argv[0] == "ssh"
    joined = " ".join(argv)
    assert "ControlMaster=auto" in joined                 # reuso de conexão (rápido)
    assert "ControlPersist=" in joined
    assert "BatchMode=yes" in joined                      # nunca trava pedindo senha interativa
    assert "StrictHostKeyChecking=accept-new" in joined
    assert "ConnectTimeout=" in joined
    assert "deploy@10.0.0.5" in argv
    assert argv[-3:] == ["bash", "-lc", "uptime"]


def test_build_argv_com_cwd_faz_cd():
    rt = RemoteTarget(alias="prod", host="h", via="tailscale", cwd="/srv/app")
    argv = rt.build_argv("git status")
    assert argv[-2] == "-lc"
    assert argv[-1] == "cd /srv/app && git status"        # cd no cwd configurado, depois o comando


def test_run_usa_runner_injetado_e_devolve_exit_e_saida():
    captured = {}

    def fake_runner(argv, **kw):
        captured["argv"] = argv
        captured["env"] = kw.get("env")

        class R:
            returncode = 0
            stdout = "saida remota\n"
            stderr = ""
        return R()

    rt = RemoteTarget(alias="prod", host="h", via="tailscale", runner=fake_runner)
    res = rt.run("echo oi")
    assert res.returncode == 0
    assert "saida remota" in res.output
    assert captured["argv"][:3] == ["tailscale", "ssh", "h"]


def test_run_ssh_com_agent_passa_ssh_auth_sock(monkeypatch):
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
    captured = {}

    def fake_runner(argv, **kw):
        captured["env"] = kw.get("env") or {}

        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    rt = RemoteTarget(alias="nas", host="h", via="ssh", ssh_agent=True, runner=fake_runner)
    rt.run("true")
    assert captured["env"].get("SSH_AUTH_SOCK") == "/tmp/agent.sock"   # opt-in → passa o agent


def test_run_sem_agent_nao_passa_ssh_auth_sock(monkeypatch):
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
    captured = {}

    def fake_runner(argv, **kw):
        captured["env"] = kw.get("env") or {}

        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    rt = RemoteTarget(alias="nas", host="h", via="ssh", ssh_agent=False, runner=fake_runner)
    rt.run("true")
    assert "SSH_AUTH_SOCK" not in captured["env"]          # default seguro: NÃO vaza o agent


def test_via_invalido_recusa():
    import pytest
    with pytest.raises(ValueError):
        RemoteTarget(alias="x", host="h", via="carrier-pigeon").build_argv("ls")
