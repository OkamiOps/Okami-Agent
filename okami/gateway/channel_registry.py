"""Registry DECLARATIVO de canais (paridade OpenClaw channel plugins): cada canal é um ChannelSpec
(módulo·classe·campos de config·superfície). Adicionar canal = registrar um spec; o builders e a
tool policy NÃO têm mais if/elif hardcoded. Telegram tem tratamento especial no builders (dedup de
token) mas mora aqui como spec p/ o mapa de superfície ser fonte única."""

from __future__ import annotations

import importlib
from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelSpec:
    name: str                       # nome do canal (= channel.name) e chave em agent.yaml
    surface: str                    # superfície p/ a tool policy (deny-by-surface)
    module: str                     # módulo da classe (import tardio — não carrega tudo no boot)
    cls: str                        # nome da classe do canal
    arg_keys: tuple[str, ...]       # campos de config POSICIONAIS, na ordem do construtor
    rest: bool = True               # REST-polling (entra no loop do builders); Telegram=False (especial)


REGISTRY: dict[str, ChannelSpec] = {
    "telegram": ChannelSpec("telegram", "telegram", "okami.channels.telegram", "TelegramChannel",
                            ("token",), rest=False),
    "slack": ChannelSpec("slack", "slack", "okami.channels.slack", "SlackChannel",
                         ("token", "channel_id")),
    "discord": ChannelSpec("discord", "discord", "okami.channels.discord", "DiscordChannel",
                           ("token", "channel_id")),
    "mattermost": ChannelSpec("mattermost", "mattermost", "okami.channels.mattermost", "MattermostChannel",
                              ("base_url", "token", "channel_id")),
}


def build_channel(ctype: str, cc: dict):
    """Instancia um canal pelo spec. KeyError(ctype) se desconhecido; KeyError(<campo>) se faltar
    campo obrigatório (o builders captura e avisa, pulando só esse canal)."""
    spec = REGISTRY.get(ctype)
    if spec is None:
        raise KeyError(ctype)
    args = []
    for k in spec.arg_keys:
        if k not in cc or cc[k] in (None, ""):
            raise KeyError(k)
        args.append(cc[k])
    cls = getattr(importlib.import_module(spec.module), spec.cls)
    return cls(*args, allow_chats=cc.get("allow_chats"), allow_all=bool(cc.get("allow_all", False)))


def rest_channel_types() -> list[str]:
    """Canais REST-polling (não-Telegram) — o loop do builders itera sobre estes."""
    return [name for name, s in REGISTRY.items() if s.rest]


def surface_map() -> dict[str, str]:
    """nome do canal → superfície (fonte única; a tool policy é validada contra isto por teste)."""
    return {s.name: s.surface for s in REGISTRY.values()}
