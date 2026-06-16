"""Display-config em tiers por plataforma (#11, port do Hermes gateway/display_config.py).

Cada plataforma tem capacidade de UX diferente: Telegram edita mensagem (status ao vivo + heartbeat);
Slack/Bolt não edita bem (sem tool_progress); SMS é só-resposta-final (MINIMAL). Em vez de mandar a
mesma verbosidade pra todo canal, resolve cada chave com precedência de 4 níveis:

    per-plataforma do usuário > global do usuário > default por plataforma > default global
"""
from __future__ import annotations

_GLOBAL_DEFAULTS: dict[str, bool] = {
    "tool_progress": True,              # mostra "🔧 rodando X" durante o turno
    "show_reasoning": False,            # NÃO vaza o pensamento por padrão
    "long_running_notifications": True,  # heartbeat "ainda trabalhando, N min"
    "interim_assistant_messages": True,  # entregas parciais
}

# Tiers: HIGH (Telegram) edita tudo; MEDIUM (Discord); LOW (Slack) sem progress; MINIMAL (SMS) só final.
_PLATFORM_DEFAULTS: dict[str, dict[str, bool]] = {
    "telegram": {},                                              # usa o global (tier HIGH)
    "discord": {"tool_progress": True},
    "slack": {"tool_progress": False, "interim_assistant_messages": False},  # Bolt não edita bem
    "sms": {"tool_progress": False, "long_running_notifications": False,
            "interim_assistant_messages": False, "show_reasoning": False},   # MINIMAL
    "webhook": {"tool_progress": False, "long_running_notifications": False},
}


def resolve_display_setting(config, platform: str, key: str):
    """Resolve `key` p/ `platform` com precedência de 4 níveis. `config` é o dict de config global do
    agente (espera-se `config['display']` com sub-dicts por plataforma + 'global')."""
    disp = {}
    if isinstance(config, dict):
        disp = config.get("display") or {}
    plat = (platform or "").lower()

    # 1) per-plataforma do usuário
    pconf = disp.get(plat)
    if isinstance(pconf, dict) and key in pconf:
        return pconf[key]
    # 2) global do usuário
    gconf = disp.get("global")
    if isinstance(gconf, dict) and key in gconf:
        return gconf[key]
    # 3) default por plataforma
    pdef = _PLATFORM_DEFAULTS.get(plat, {})
    if key in pdef:
        return pdef[key]
    # 4) default global
    return _GLOBAL_DEFAULTS.get(key)


__all__ = ["resolve_display_setting"]
