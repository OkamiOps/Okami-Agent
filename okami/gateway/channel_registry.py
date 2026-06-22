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
    # Campos de config KEYWORD-ONLY (alguns canais — ex.: e-mail — têm construtor `*, user, app_password`):
    # a chave do dict de config já É o nome do kwarg. Quando vazio (default), o canal é posicional (arg_keys).
    kwarg_keys: tuple[str, ...] = ()
    required_keys: tuple[str, ...] = ()   # subconjunto OBRIGATÓRIO dos kwargs (build_channel valida)


REGISTRY: dict[str, ChannelSpec] = {
    "telegram": ChannelSpec("telegram", "telegram", "okami.channels.telegram", "TelegramChannel",
                            ("token",), rest=False,
                            hint="Você está no Telegram: escreva em MARKDOWN simples — **negrito**, "
                                 "_itálico_, `código`, ```bloco```, [texto](url). NÃO escreva HTML cru "
                                 "(<b>, <code>) nem tabela markdown (pipe) — prefira listas 'rótulo: valor'."),
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
    # E-mail (item 19): construtor KEYWORD-ONLY (`*, user, app_password, imap_host, …`) → passa por
    # kwarg_keys, não por arg_keys. O builders parseia channels.email com config.parse_email_channel
    # (resolve app-password via env/secret_sources, normaliza host/port) ANTES de chamar build_channel.
    "email": ChannelSpec("email", "email", "okami.channels.email", "EmailChannel",
                         arg_keys=(),
                         kwarg_keys=("user", "app_password", "imap_host", "imap_port",
                                     "smtp_host", "smtp_port", "mailbox", "poll_interval"),
                         required_keys=("user", "app_password"),
                         hint="Você está no e-mail (texto puro): sem markdown/HTML — escreva em "
                              "texto corrido, parágrafos curtos; nada de tabela ou ** asterisco **."),
    # Canais regionais asiáticos (#19) — OUTBOUND (notificação): o agente publica no grupo/canal.
    "dingtalk": ChannelSpec("dingtalk", "dingtalk", "okami.channels.regional", "DingTalkChannel",
                            ("token", "channel_id"),
                            hint="Você está no DingTalk (texto): sem markdown rico; mensagem objetiva."),
    "wecom": ChannelSpec("wecom", "wecom", "okami.channels.regional", "WeComChannel",
                         ("key", "channel_id"),
                         hint="Você está no WeCom/WeChat Work (texto): conciso, sem markdown rico."),
    "qqbot": ChannelSpec("qqbot", "qqbot", "okami.channels.regional", "QQBotChannel",
                         ("token", "channel_id"),
                         hint="Você está no QQ (texto): mensagem curta e direta."),
    # Mensageria global/aberta (#19) — OUTBOUND (notificação): o agente manda mensagem.
    "whatsapp": ChannelSpec("whatsapp", "whatsapp", "okami.channels.messaging", "WhatsAppChannel",
                            ("token", "phone_id", "channel_id"),
                            hint="Você está no WhatsApp (texto): sem markdown; mensagem curta e clara."),
    "signal": ChannelSpec("signal", "signal", "okami.channels.messaging", "SignalChannel",
                          ("api_url", "number", "channel_id"),
                          hint="Você está no Signal (texto): sem markdown; objetivo."),
    "matrix": ChannelSpec("matrix", "matrix", "okami.channels.messaging", "MatrixChannel",
                          ("homeserver", "token", "channel_id"),
                          hint="Você está no Matrix (markdown leve ok): conciso."),
    "sms": ChannelSpec("sms", "sms", "okami.channels.messaging", "SMSChannel",
                       ("api_url", "from_number", "channel_id"),
                       hint="Você está no SMS (texto puro, curto): uma ou duas frases, sem markdown."),
    "bluebubbles": ChannelSpec("bluebubbles", "bluebubbles", "okami.channels.messaging", "BlueBubblesChannel",
                               ("server_url", "password", "channel_id"),
                               hint="Você está no iMessage (texto): natural e curto."),
    "weixin": ChannelSpec("weixin", "weixin", "okami.channels.messaging", "WeixinChannel",
                          ("access_token", "channel_id"),
                          hint="Você está no WeChat (texto): conciso, sem markdown rico."),
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
    # Canal KEYWORD-ONLY (ex.: e-mail): só passa os kwargs PRESENTES (o resto cai no default do
    # construtor); valida os obrigatórios (required_keys) com a mesma KeyError(<campo>) que o
    # builders captura p/ pular só esse canal.
    kwargs = {}
    for k in spec.kwarg_keys:
        if k in cc and cc[k] not in (None, ""):
            kwargs[k] = cc[k]
    for k in spec.required_keys:
        if k not in kwargs:
            raise KeyError(k)
    cls = getattr(importlib.import_module(spec.module), spec.cls)
    return cls(*args, allow_chats=cc.get("allow_chats"), allow_all=bool(cc.get("allow_all", False)),
               **kwargs)


def rest_channel_types() -> list[str]:
    """Canais REST-polling (não-Telegram) — o loop do builders itera sobre estes."""
    return [name for name, s in REGISTRY.items() if s.rest]


def surface_map() -> dict[str, str]:
    """nome do canal → superfície (fonte única; a tool policy é validada contra isto por teste)."""
    return {s.name: s.surface for s in REGISTRY.values()}
