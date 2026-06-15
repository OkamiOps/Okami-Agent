"""Tools remote_connect / remote_disconnect — o agente entra/sai de um host, com a allowlist por
superfície e health-check (não conecta se o host não responde). Persiste via hook ctx.set_remote.
"""
from __future__ import annotations

from types import SimpleNamespace

import okami.integrations.remote as rem
from okami.core.tools import ToolContext, default_registry
from okami.core.tools.remote import RemoteConnect, RemoteDisconnect


def _ok(argv, **kw):
    class R:
        returncode = 0
        stdout = "okami-remote-ok\n"
        stderr = ""
    return R()


def _cfg(hosts=None, ssh_agent=False):
    return SimpleNamespace(remote={"hosts": hosts or {}, "ssh_agent": ssh_agent})


def test_connect_alias_seta_remote(monkeypatch, tmp_path):
    monkeypatch.setattr(rem.subprocess, "run", _ok)
    ctx = ToolContext(workspace=tmp_path, surface="cli",
                      cfg=_cfg({"prod": {"host": "prod-server", "via": "tailscale"}}))
    res = RemoteConnect().run({"host": "prod"}, ctx)
    assert res.ok and res.effect
    assert ctx.remote is not None and ctx.remote.host == "prod-server"
    assert "prod" in res.output


def test_connect_host_cru_no_telegram_recusado(monkeypatch, tmp_path):
    monkeypatch.setattr(rem.subprocess, "run", _ok)
    ctx = ToolContext(workspace=tmp_path, surface="telegram", cfg=_cfg(), open_fs=False)
    res = RemoteConnect().run({"host": "qualquer-vm"}, ctx)
    assert res.ok is False
    assert ctx.remote is None                            # allowlist barrou no canal remoto (open_fs=False)


def test_connect_host_cru_no_terminal_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(rem.subprocess, "run", _ok)
    ctx = ToolContext(workspace=tmp_path, open_fs=True, cfg=_cfg())   # dono no CLI interativo
    res = RemoteConnect().run({"host": "minha-vm"}, ctx)
    assert res.ok and ctx.remote.host == "minha-vm"      # livre no terminal (open_fs=True)


def test_connect_health_falha_nao_conecta(monkeypatch, tmp_path):
    def _bad(argv, **kw):
        class R:
            returncode = 255
            stdout = ""
            stderr = "Connection refused"
        return R()
    monkeypatch.setattr(rem.subprocess, "run", _bad)
    ctx = ToolContext(workspace=tmp_path, surface="cli", cfg=_cfg({"prod": {"host": "h"}}))
    res = RemoteConnect().run({"host": "prod"}, ctx)
    assert res.ok is False and ctx.remote is None         # health falhou → não conecta


def test_connect_persist_hook(monkeypatch, tmp_path):
    monkeypatch.setattr(rem.subprocess, "run", _ok)
    saved = []
    ctx = ToolContext(workspace=tmp_path, surface="cli", cfg=_cfg({"prod": {"host": "h"}}),
                      set_remote=lambda rt: saved.append(rt))
    RemoteConnect().run({"host": "prod"}, ctx)
    assert len(saved) == 1 and saved[0].host == "h"       # persiste na sessão (sobrevive ao turno)


def test_disconnect_volta_pro_local(monkeypatch, tmp_path):
    monkeypatch.setattr(rem.subprocess, "run", _ok)
    saved = []
    ctx = ToolContext(workspace=tmp_path, surface="cli", cfg=_cfg({"prod": {"host": "h"}}),
                      set_remote=lambda rt: saved.append(rt))
    RemoteConnect().run({"host": "prod"}, ctx)
    res = RemoteDisconnect().run({}, ctx)
    assert res.ok and ctx.remote is None
    assert saved[-1] is None                             # persist(None) — limpa a sessão


def test_registradas_no_default_registry():
    r = default_registry()
    assert "remote_connect" in r and "remote_disconnect" in r
