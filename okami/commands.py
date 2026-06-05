"""Declarative slash-command registry (Hermes practice — the `CommandDef`).

One definition per command yields: help, /commands, autocomplete, dispatch and "did you mean".
Adding a command = one line here + a handler in the gateway. Aliases, category and tier come for free.

i18n: English is the DEFAULT and the source of truth (the `desc` below). Other locales override per
command via the catalog key `cmd.<name>` (and `cmd.cat.<key>` for category labels) — see okami/locales.
Render through `desc_of(c)` / `category_label(key)`, never `c.desc` directly, so it localizes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandDef:
    name: str                         # canonical, no "/" (e.g. "new")
    desc: str                         # English default (source of truth); PT etc. via catalog cmd.<name>
    category: str                     # session | model | identity | info | system  (stable key)
    aliases: tuple[str, ...] = ()
    args: str = ""                    # short hint (e.g. "<level>")
    tier: str = "standard"            # essential | standard | power (progressive disclosure)
    scope: str = "both"              # both | chat (TUI/REPL only) | cli


# Order = display order within the category.
COMMAND_REGISTRY: list[CommandDef] = [
    # ---- session ----
    CommandDef("new", "start a new conversation (archives the current one)", "session", ("reset",), tier="essential"),
    CommandDef("stop", "cancel the running task", "session", ("cancel", "parar"), tier="essential"),
    CommandDef("retry", "resume the last interrupted task", "session", ("continuar",)),
    CommandDef("compact", "compact the context now (summarize what happened)", "session"),
    CommandDef("sessions", "list archived conversations (from /new)", "session", ("ls",)),
    CommandDef("resume", "resume an archived conversation (/resume <n>)", "session", args="<n>"),
    CommandDef("export", "export the current conversation as Markdown (/export [file])", "session", args="[file]"),
    CommandDef("topic", "parallel conversations in the same chat (Telegram topics = separate sessions)", "session",
               tier="power"),
    CommandDef("background", "run a task in parallel and notify you when it's done", "session",
               ("bg",), args="<task>"),
    CommandDef("process", "OS process supervision (server/build): status·log·immediate kill", "session",
               ("proc",), args="<status|log|kill|signal> [id]", tier="power"),
    CommandDef("title", "name the current conversation (/title <name>)", "session", args="[name]"),
    CommandDef("exit", "leave the chat", "session", ("quit", "sair"), scope="chat", tier="essential"),
    # ---- model / reasoning ----
    CommandDef("model", "show or switch this session's model", "model", ("m",), args="[id]", tier="essential"),
    CommandDef("models", "list available models", "model"),
    CommandDef("think", "reasoning effort (minimal·low·medium·high·off)", "model",
               ("reasoning",), args="<level>"),
    # ---- identity / taste ----
    CommandDef("feedback", "shape how the agent talks (evolves VOICE/PERSONA)", "identity",
               args="<text>"),
    CommandDef("persona", "change the tone for this session only (/persona off reverts)", "identity", args="<preset>"),
    CommandDef("undo", "revert the last identity evolution", "identity", ("rollback",)),
    CommandDef("like", "liked the design (taste)", "identity", args="<desc>", tier="power"),
    CommandDef("dislike", "disliked the design (taste)", "identity", args="<desc>", tier="power"),
    CommandDef("different", "want a different design (taste)", "identity", args="<desc>", tier="power"),
    # ---- info ----
    CommandDef("help", "show the essential commands", "info", ("?", "start"), tier="essential"),
    CommandDef("commands", "list ALL commands by category", "info"),
    CommandDef("status", "session state (turns, model, yolo)", "info", tier="essential"),
    CommandDef("usage", "tokens + accumulated cost for the session", "info"),
    CommandDef("tools", "list the tools the agent has", "info"),
    CommandDef("details", "tool-call verbosity: hidden | collapsed | expanded", "info",
               args="[level]", scope="chat", tier="power"),
    CommandDef("agents", "activity panel: current turn, /background and queue", "info", ("tasks",),
               scope="chat", tier="power"),
    CommandDef("skin", "switch the TUI theme (okami | nord | dracula | …)", "info", args="[theme]",
               scope="chat", tier="power"),
    CommandDef("mouse", "toggle the TUI mouse (off = native terminal selection)", "info",
               args="[on|off]", scope="chat", tier="power"),
    CommandDef("whoami", "show your chat id (for the allowlist)", "info", ("id",), tier="power"),
    # ---- system ----
    CommandDef("yolo", "auto-approve sensitive actions this session", "system"),
    CommandDef("normal", "back to normal approval", "system"),
    CommandDef("voice", "toggle audio replies (TTS) this session", "system", args="[on|off]"),
    CommandDef("busy", "what to do if you type while busy: queue | interrupt", "system",
               args="[mode]"),
    CommandDef("sethome", "set this chat as the target for reminders/schedules (cron)", "system",
               tier="power"),
    CommandDef("config", "show the effective config (secrets masked)", "system", tier="power"),
    CommandDef("reload", "hot-reload the config (without restarting)", "system", ("reloadconfig",), tier="power"),
]

CATEGORY_ORDER = ["session", "model", "identity", "info", "system"]

_LOOKUP: dict[str, CommandDef] = {}
for _c in COMMAND_REGISTRY:
    for _nm in (_c.name, *_c.aliases):
        _LOOKUP[_nm] = _c


# --- i18n helpers (localize at render time; English = the registry default) -------------------------

def desc_of(c: CommandDef) -> str:
    """Localized description for a command. EN comes from the registry; other locales from cmd.<name>."""
    from okami import i18n
    return i18n._catalog(i18n.current_lang()).get(f"cmd.{c.name}") or c.desc


def category_label(key: str) -> str:
    """Localized category label. EN = the key itself (session/model/…); others from cmd.cat.<key>."""
    from okami import i18n
    return i18n._catalog(i18n.current_lang()).get(f"cmd.cat.{key}") or key


def resolve(token: str) -> CommandDef | None:
    """'/New' or 'reset' → the canonical CommandDef. Strips '/' and case. None if unknown."""
    return _LOOKUP.get(token.strip().lstrip("/").lower())


def suggest(token: str, limit: int = 4) -> list[str]:
    """Canonical names whose prefix matches — for 'did you mean …?'."""
    t = token.strip().lstrip("/").lower()
    if not t:
        return []
    hits = {c.name for k, c in _LOOKUP.items() if k.startswith(t)}
    if not hits:                                  # nothing by prefix → try substring (typo in the middle)
        hits = {c.name for k, c in _LOOKUP.items() if t in k}
    return sorted(hits)[:limit]


def by_category(tier: str | None = None) -> dict[str, list[CommandDef]]:
    """Commands grouped by category (in CATEGORY_ORDER). tier='essential' filters."""
    out: dict[str, list[CommandDef]] = {}
    for c in COMMAND_REGISTRY:
        if tier == "essential" and c.tier != "essential":
            continue
        out.setdefault(c.category, []).append(c)
    return {cat: out[cat] for cat in CATEGORY_ORDER if cat in out}


def all_slash_names(scope: str | None = None) -> list[str]:
    """['/new','/stop',…] for autocomplete (includes aliases). scope='chat' includes chat+both."""
    names: list[str] = []
    for c in COMMAND_REGISTRY:
        if scope and c.scope not in (scope, "both"):
            continue
        names += ["/" + c.name, *("/" + a for a in c.aliases)]
    return names


def telegram_menu() -> list[dict]:
    """[{command, description}] for Telegram setMyCommands (the '/' button menu). No aliases; skips
    chat-only commands (e.g. /exit). Name ≤32 and description ≤256 (API limits). Description localized."""
    out = []
    for c in COMMAND_REGISTRY:
        if c.scope == "chat":                         # /exit /quit make no sense on Telegram
            continue
        out.append({"command": c.name[:32], "description": (desc_of(c) or c.name)[:256]})
    return out[:100]                                  # Telegram limit


def help_lines(essential_only: bool = False) -> list[str]:
    """'category: /a /b …' lines for text help (Telegram/console). Category labels localized."""
    cats = by_category(tier="essential" if essential_only else None)
    lines = []
    for cat, cmds in cats.items():
        parts = ", ".join("/" + c.name + (f" {c.args}" if c.args else "") for c in cmds)
        lines.append(f"{category_label(cat)}: {parts}")
    return lines
