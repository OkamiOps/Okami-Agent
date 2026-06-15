"""Regressões de segurança do ambiente remoto (achados da caça adversarial #remote).

#4 build_config preserva cfg.remote (sem isto a allowlist/hosts são código morto).
#1/#6/#11 o sinal de "dono presente" (host cru livre) é open_fs — fail-SAFE (default False), não a
superfície (defaultável p/ 'cli'). Job autônomo (scheduler/cron, open_fs=False) NÃO é terminal →
allowlist vale → sem lavagem de superfície.
#3 saída remota gigante é CAPADA (anti-OOM). #9 remote.hosts malformado não quebra.
"""
from __future__ import annotations

from types import SimpleNamespace

import okami.integrations.remote as rem
from okami.core.tools import ToolContext
from okami.core.tools.remote import RemoteConnect


def _ok(argv, **kw):
    class R:
        returncode = 0
        stdout = "okami-remote-ok\n"
        stderr = ""
    return R()


def _cfg(hosts=None, ssh_agent=False):
    return SimpleNamespace(remote={"hosts": hosts or {}, "ssh_agent": ssh_agent})


# ── #4 build_config preserva remote ──
def test_build_config_preserva_remote():
    from okami.config import build_config
    cfg = build_config({"default_provider": "p", "providers": {"p": {"model": "m"}},
                        "remote": {"hosts": {"prod": {"host": "prod-server"}}, "ssh_agent": True}})
    assert cfg.remote["hosts"]["prod"]["host"] == "prod-server"
    assert cfg.remote["ssh_agent"] is True


# ── #1/#11 sinal de terminal = open_fs (fail-safe), não surface ──
def test_host_cru_so_no_open_fs_dono(monkeypatch, tmp_path):
    monkeypatch.setattr(rem.subprocess, "run", _ok)
    # open_fs=True (dono no CLI interativo) → host cru liberado
    ctx = ToolContext(workspace=tmp_path, cfg=_cfg(), open_fs=True)
    assert RemoteConnect().run({"host": "minha-vm"}, ctx).ok is True


def test_host_cru_sem_open_fs_recusado_mesmo_surface_cli(monkeypatch, tmp_path):
    monkeypatch.setattr(rem.subprocess, "run", _ok)
    # surface='cli' MAS open_fs=False (job autônomo/scheduler) → allowlist vale → host cru RECUSADO
    ctx = ToolContext(workspace=tmp_path, cfg=_cfg(), surface="cli", open_fs=False)
    res = RemoteConnect().run({"host": "user@1.2.3.4"}, ctx)
    assert res.ok is False and ctx.remote is None        # sem lavagem de superfície


def test_alias_funciona_sem_open_fs(monkeypatch, tmp_path):
    monkeypatch.setattr(rem.subprocess, "run", _ok)
    # alias allowlisted continua funcionando em job autônomo (open_fs=False)
    ctx = ToolContext(workspace=tmp_path, cfg=_cfg({"prod": {"host": "h"}}), open_fs=False)
    assert RemoteConnect().run({"host": "prod"}, ctx).ok is True


# ── #3 saída remota CAPADA (anti-OOM) ──
def test_saida_remota_capada():
    from okami.integrations.remote import RemoteTarget

    def _huge(argv, **kw):
        class R:
            returncode = 0
            stdout = "x" * 5_000_000              # 5 MB de saída
            stderr = ""
        return R()
    rt = RemoteTarget(alias="h", host="h", runner=_huge)
    res = rt.run("yes")
    assert len(res.output) < 1_000_000            # capado, não bufferiza/devolve tudo


# ── #7 redact mascara chave PEM + credencial em URL (barreira de saída do shell remoto) ──
def test_redact_mascara_pem_e_url_cred():
    from okami.core.redact import redact
    pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nMIIEsegredo123abc\n-----END OPENSSH PRIVATE KEY-----"  # pragma: allowlist secret
    assert "MIIEsegredo123abc" not in redact(pem)
    out = redact("postgres://admin:s3cr3tPass@db.host:5432/x")
    assert "s3cr3tPass" not in out and "admin" in out      # mascara só a senha, mantém o user/host


# ── #9 remote.hosts malformado não quebra ──
def test_hosts_malformado_nao_quebra(monkeypatch, tmp_path):
    monkeypatch.setattr(rem.subprocess, "run", _ok)
    ctx = ToolContext(workspace=tmp_path, cfg=SimpleNamespace(remote={"hosts": ["lista", "errada"]}),
                      open_fs=False)
    res = RemoteConnect().run({"host": "prod"}, ctx)      # hosts é lista (não dict) → não AttributeError
    assert res.ok is False                                # recusa limpa (não é alias, sem open_fs)
