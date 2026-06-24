"""Config-drop trap (hunt#3): bloco do yaml SEM campo no OkamiConfig é DESCARTADO por build_config → feature
nasce MORTA. mixture (MoA), security (supply-chain/lazy-deps), notifications (desktop) eram lidos via
getattr(cfg, X) mas nunca chegavam. (channels fica DE FORA de propósito: contém token=segredo.)"""
from __future__ import annotations

from okami.config import build_config

_RAW = {
    "default_provider": "p",
    "providers": {"p": {"model": "m"}},
    "mixture": {"reference_providers": ["a", "b"]},
    "security": {"advisories": True},
    "notifications": {"desktop": True},
    "channels": {"telegram": {"token": "SECRET"}},
}


def test_mixture_security_notifications_survive_build_config():
    cfg = build_config(_RAW)
    assert cfg.mixture == {"reference_providers": ["a", "b"]}
    assert cfg.security == {"advisories": True}
    assert cfg.notifications == {"desktop": True}


def test_channels_stays_out_of_okamiconfig():
    cfg = build_config(_RAW)
    assert not hasattr(cfg, "channels")          # token=segredo NUNCA no OkamiConfig (constraint de segurança)
