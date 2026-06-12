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
    hint: str = ""                  # dica de formatação injetada no system prompt (item 22)


REGISTRY: dict[str, ChannelSpec] = {
    "telegram": ChannelSpec("telegram", "telegram", "okami.channels.telegram", "TelegramChannel",
                            ("token",), rest=False,
                            hint="Você está no Telegram (HTML): use <b>negrito</b>, <i>itálico</i>, "
                                 "<code>código</code>, <pre>bloco</pre>. NÃO use tabela markdown (pipe) "
                                 "— vira texto cru; prefira listas 'rótulo: valor'."),
    "slack": ChannelSpec("slack", "slack", "okami.channels.slack", "SlackChannel",
                         ("token", "channel_id"),
                         hint="Você está no Slack (mrkdwn): *negrito*, _itálico_, `código`. Sem tabela "
                              "markdown; use listas curtas."),
    "discord": ChannelSpec("discord", "discord", "okami.channels.discord", "DiscordChannel",
                           ("token", "channel_id"),
                           hint="Você está no Discord (markdown): **negrito**, *itálico*, ```bloco```. "
                                "Mensagem ≤2000 chars; seja conciso."),
    "mattermost": ChannelSpec("mattermost", "mattermost", "okami.channels.mattermost", "MattermostChannel",
                              ("base_url", "token", "channel_id"),
                              hint="Você está no Mattermost (markdown): **negrito**, `código`, tabelas ok."),
}

# Telegram em GRUPO é a mesma plataforma (superfície 'group') → herda o hint do telegram.
_SURFACE_ALIAS = {"group": "telegram"}


def platform_hint(surface: str) -> str:
    """Dica de formatação da plataforma p/ a superfície (item 22). '' p/ CLI/desconhecida (sem custo)."""
    target = _SURFACE_ALIAS.get(surface, surface)
    for s in REGISTRY.values():
        if s.surface == target and s.hint:
            return s.hint
    return ""


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
