"""run_shell roteia pro host remoto quando ctx.remote está setado — MAS as guardas de segurança
(hardline, jail de path sensível) disparam ANTES de sair pela rede.
"""
from __future__ import annotations

from okami.core.tools import ToolContext
from okami.core.tools.files import RunShell
from okami.integrations.remote import RemoteResult


class _FakeRemote:
    alias = "prod"

    def __init__(self):
        self.calls = []

    def run(self, cmd, timeout=None):
        self.calls.append(cmd)
        return RemoteResult(0, "saida da maquina remota")


def test_run_shell_vai_pro_remoto_quando_conectado(tmp_path):
    rem = _FakeRemote()
    ctx = ToolContext(workspace=tmp_path, remote=rem)
    res = RunShell().run({"cmd": "ls -la"}, ctx)
    assert res.ok
    assert "saida da maquina remota" in res.output
    assert "prod" in res.output                          # marca que rodou remoto (📡 prod)
    assert rem.calls == ["ls -la"]                       # foi pro remoto, NÃO rodou local


def test_run_shell_local_quando_sem_remoto(tmp_path):
    ctx = ToolContext(workspace=tmp_path)                # remote=None → comportamento atual
    res = RunShell().run({"cmd": "echo ola-local"}, ctx)
    assert res.ok and "ola-local" in res.output


def test_hardline_bloqueia_mesmo_remoto(tmp_path):
    rem = _FakeRemote()
    ctx = ToolContext(workspace=tmp_path, remote=rem)
    res = RunShell().run({"cmd": "rm -rf /"}, ctx)
    assert res.ok is False
    assert rem.calls == []                               # hardline barrou ANTES de ir pro remoto


def test_jail_path_sensivel_bloqueia_remoto(tmp_path):
    rem = _FakeRemote()
    ctx = ToolContext(workspace=tmp_path, remote=rem)
    res = RunShell().run({"cmd": "cat ~/.ssh/id_rsa"}, ctx)
    assert res.ok is False                               # .ssh/id_rsa barrado mesmo remoto
    assert rem.calls == []


def test_toolcontext_remote_default_none(tmp_path):
    ctx = ToolContext(workspace=tmp_path)
    assert ctx.remote is None
    assert ctx.surface == "cli"
