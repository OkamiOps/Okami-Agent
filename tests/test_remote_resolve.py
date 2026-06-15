"""resolve_remote — traduz um alias/host + a config num RemoteTarget, APLICANDO a allowlist.

Regra de segurança (decisão do design): no TERMINAL (dono presente) o host é livre; numa superfície
REMOTA (Telegram/etc.) só alias em remote.hosts passa — host cru é recusado.
"""
from __future__ import annotations

import pytest

from okami.integrations.remote import resolve_remote

_CFG = {
    "hosts": {
        "prod": {"host": "prod-server", "via": "tailscale", "cwd": "/srv/app"},
        "nas": {"host": "deploy@10.0.0.5", "via": "ssh"},
    },
    "ssh_agent": True,
}


def test_alias_resolve_para_o_host_configurado():
    rt = resolve_remote(_CFG, "prod", is_terminal=True)
    assert rt.host == "prod-server" and rt.via == "tailscale" and rt.cwd == "/srv/app"
    assert rt.alias == "prod"


def test_alias_propaga_ssh_agent_da_config():
    rt = resolve_remote(_CFG, "nas", is_terminal=False)    # alias liberado mesmo no remoto
    assert rt.via == "ssh" and rt.ssh_agent is True


def test_host_cru_no_terminal_e_livre():
    rt = resolve_remote(_CFG, "minha-vm", is_terminal=True)
    assert rt.host == "minha-vm" and rt.via == "tailscale"   # bare name → tailscale


def test_host_cru_com_arroba_vira_ssh():
    rt = resolve_remote(_CFG, "user@1.2.3.4", is_terminal=True)
    assert rt.via == "ssh" and rt.host == "user@1.2.3.4"


def test_host_cru_no_remoto_e_RECUSADO():
    with pytest.raises(ValueError, match="allowlist|não liberado|remote.hosts"):
        resolve_remote(_CFG, "qualquer-vm", is_terminal=False)


def test_alias_desconhecido_no_remoto_recusado():
    # alias que não existe vira "host cru" → no remoto, recusa
    with pytest.raises(ValueError):
        resolve_remote(_CFG, "inexistente", is_terminal=False)


def test_sem_allowlist_terminal_ainda_livre():
    rt = resolve_remote({}, "alguma-maquina", is_terminal=True)
    assert rt.host == "alguma-maquina"


def test_sem_allowlist_remoto_recusa_tudo():
    with pytest.raises(ValueError):
        resolve_remote({}, "alguma-maquina", is_terminal=False)


# ── injeção de argumento (host começando com '-' = ssh -oProxyCommand=... → RCE local) ──
def test_host_com_traco_inicial_recusado():
    with pytest.raises(ValueError, match="inválido|-"):
        resolve_remote({}, "-oProxyCommand=touch /tmp/pwned", is_terminal=True)


def test_host_com_espaco_recusado():
    with pytest.raises(ValueError):
        resolve_remote({}, "host com espaco", is_terminal=True)


def test_alias_com_host_malicioso_na_config_recusado():
    # mesmo via alias (config do dono), host começando com '-' é neutralizado no build do argv
    import pytest as _pytest
    rt = resolve_remote({"hosts": {"x": {"host": "-oProxyCommand=evil"}}}, "x", is_terminal=False)
    with _pytest.raises(ValueError):
        rt.build_argv("ls")          # defesa em profundidade: base_argv recusa host hostil
