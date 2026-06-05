"""Registro DECLARATIVO de slash commands (prática do Hermes — o `CommandDef`).

Uma definição por comando vira: help, /commands, autocomplete, dispatch e "did you mean".
Adicionar comando = uma linha aqui + um handler no gateway. Aliases, categoria e tier saem de graça.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandDef:
    name: str                         # canônico, sem "/" (ex.: "new")
    desc: str
    category: str                     # sessão | modelo | identidade | info | sistema
    aliases: tuple[str, ...] = ()
    args: str = ""                    # hint curto (ex.: "<nível>")
    tier: str = "standard"            # essential | standard | power (disclosure progressivo)
    scope: str = "both"              # both | chat (só TUI/REPL) | cli


# Ordem = ordem de exibição dentro da categoria.
COMMAND_REGISTRY: list[CommandDef] = [
    # ---- sessão ----
    CommandDef("new", "começa uma conversa nova (arquiva a atual)", "sessão", ("reset",), tier="essential"),
    CommandDef("stop", "cancela a tarefa em andamento", "sessão", ("cancel", "parar"), tier="essential"),
    CommandDef("retry", "retoma a última tarefa interrompida", "sessão", ("continuar",)),
    CommandDef("compact", "compacta o contexto agora (resume o que já passou)", "sessão"),
    CommandDef("sessions", "lista as conversas arquivadas (por /new)", "sessão", ("ls",)),
    CommandDef("resume", "retoma uma conversa arquivada (/resume <n>)", "sessão", args="<n>"),
    CommandDef("export", "exporta a conversa atual em Markdown (/export [arquivo])", "sessão", args="[arquivo]"),
    CommandDef("topic", "conversas paralelas no mesmo chat (tópicos do Telegram = sessões separadas)", "sessão",
               tier="power"),
    CommandDef("background", "roda uma tarefa em paralelo e avisa quando terminar", "sessão",
               ("bg",), args="<tarefa>"),
    CommandDef("process", "supervisão de processos OS (servidor/build): status·log·kill imediato", "sessão",
               ("proc",), args="<status|log|kill|signal> [id]", tier="power"),
    CommandDef("title", "dá um nome à conversa atual (/title <nome>)", "sessão", args="[nome]"),
    CommandDef("exit", "sai do chat", "sessão", ("quit", "sair"), scope="chat", tier="essential"),
    # ---- modelo / raciocínio ----
    CommandDef("model", "mostra ou troca o modelo desta sessão", "modelo", ("m",), args="[id]", tier="essential"),
    CommandDef("models", "lista os modelos disponíveis", "modelo"),
    CommandDef("think", "esforço de raciocínio (minimal·low·medium·high·off)", "modelo",
               ("reasoning",), args="<nível>"),
    # ---- identidade / gosto ----
    CommandDef("feedback", "molda o jeito do agente falar (evolui VOICE/PERSONA)", "identidade",
               args="<texto>"),
    CommandDef("persona", "muda o tom só nesta sessão (/persona off volta)", "identidade", args="<preset>"),
    CommandDef("undo", "reverte a última evolução de identidade", "identidade", ("rollback",)),
    CommandDef("like", "curtiu o design (taste)", "identidade", args="<desc>", tier="power"),
    CommandDef("dislike", "não curtiu o design (taste)", "identidade", args="<desc>", tier="power"),
    CommandDef("different", "quer um design diferente (taste)", "identidade", args="<desc>", tier="power"),
    # ---- info ----
    CommandDef("help", "mostra os comandos essenciais", "info", ("?", "start"), tier="essential"),
    CommandDef("commands", "lista TODOS os comandos por categoria", "info"),
    CommandDef("status", "estado da sessão (trocas, modelo, yolo)", "info", tier="essential"),
    CommandDef("usage", "tokens + custo acumulados da sessão", "info"),
    CommandDef("tools", "lista as ferramentas que o agente tem", "info"),
    CommandDef("details", "verbosidade dos tool-calls: hidden | collapsed | expanded", "info",
               args="[nível]", scope="chat", tier="power"),
    CommandDef("agents", "painel de atividade: turno, /background e fila", "info", ("tasks",),
               scope="chat", tier="power"),
    CommandDef("skin", "troca o tema da TUI (okami | nord | dracula | …)", "info", args="[tema]",
               scope="chat", tier="power"),
    CommandDef("mouse", "liga/desliga o mouse da TUI (off = seleção nativa do terminal)", "info",
               args="[on|off]", scope="chat", tier="power"),
    CommandDef("whoami", "mostra seu chat id (p/ allowlist)", "info", ("id",), tier="power"),
    # ---- sistema ----
    CommandDef("yolo", "auto-aprova ações sensíveis nesta sessão", "sistema"),
    CommandDef("normal", "volta a aprovação normal", "sistema"),
    CommandDef("voice", "liga/desliga a resposta em áudio (TTS) nesta sessão", "sistema", args="[on|off]"),
    CommandDef("busy", "o que fazer se você escrever ocupado: queue (fila) | interrupt (corta)", "sistema",
               args="[modo]"),
    CommandDef("sethome", "define este chat como destino dos lembretes/agendamentos (cron)", "sistema",
               tier="power"),
    CommandDef("config", "mostra a config efetiva (segredos mascarados)", "sistema", tier="power"),
    CommandDef("reload", "recarrega a config em quente (sem reiniciar)", "sistema", ("reloadconfig",), tier="power"),
]

CATEGORY_ORDER = ["sessão", "modelo", "identidade", "info", "sistema"]

_LOOKUP: dict[str, CommandDef] = {}
for _c in COMMAND_REGISTRY:
    for _nm in (_c.name, *_c.aliases):
        _LOOKUP[_nm] = _c


def resolve(token: str) -> CommandDef | None:
    """'/New' ou 'reset' → o CommandDef canônico. Tira '/' e caso. None se não for comando conhecido."""
    return _LOOKUP.get(token.strip().lstrip("/").lower())


def suggest(token: str, limit: int = 4) -> list[str]:
    """Nomes canônicos cujo prefixo casa — p/ 'você quis dizer …?'."""
    t = token.strip().lstrip("/").lower()
    if not t:
        return []
    hits = {c.name for k, c in _LOOKUP.items() if k.startswith(t)}
    if not hits:                                  # nada por prefixo → tenta substring (typo no meio)
        hits = {c.name for k, c in _LOOKUP.items() if t in k}
    return sorted(hits)[:limit]


def by_category(tier: str | None = None) -> dict[str, list[CommandDef]]:
    """Comandos agrupados por categoria (na ordem de CATEGORY_ORDER). tier='essential' filtra."""
    out: dict[str, list[CommandDef]] = {}
    for c in COMMAND_REGISTRY:
        if tier == "essential" and c.tier != "essential":
            continue
        out.setdefault(c.category, []).append(c)
    return {cat: out[cat] for cat in CATEGORY_ORDER if cat in out}


def all_slash_names(scope: str | None = None) -> list[str]:
    """['/new','/stop',…] p/ o autocomplete (inclui aliases). scope='chat' inclui chat+both."""
    names: list[str] = []
    for c in COMMAND_REGISTRY:
        if scope and c.scope not in (scope, "both"):
            continue
        names += ["/" + c.name, *("/" + a for a in c.aliases)]
    return names


def telegram_menu() -> list[dict]:
    """[{command, description}] p/ o setMyCommands do Telegram (o menu do botão '/'). Sem aliases;
    pula comandos só-do-chat (ex.: /exit). Nome ≤32 e descrição ≤256 (limites da API)."""
    out = []
    for c in COMMAND_REGISTRY:
        if c.scope == "chat":                         # /exit /quit não fazem sentido no Telegram
            continue
        out.append({"command": c.name[:32], "description": (c.desc or c.name)[:256]})
    return out[:100]                                  # limite do Telegram


def help_lines(essential_only: bool = False) -> list[str]:
    """Linhas 'categoria: /a /b …' p/ help em texto (Telegram/console)."""
    cats = by_category(tier="essential" if essential_only else None)
    lines = []
    for cat, cmds in cats.items():
        parts = ", ".join("/" + c.name + (f" {c.args}" if c.args else "") for c in cmds)
        lines.append(f"{cat}: {parts}")
    return lines
