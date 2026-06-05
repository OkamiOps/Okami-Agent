"""Tool policy POR SUPERFÍCIE/agente (P1.4) — a mesma tool surface NÃO serve pra tudo.

OpenClaw resolve policy por superfície (CLI local, Telegram, grupo, subagente, Paperclip…). Aqui o
registro de tools (#14) é FILTRADO por superfície: Telegram não roda shell por padrão, grupo é ainda
mais restrito, subagente não dá `spawn` (anti-recursão). As tools TERMINAIS (respond/task_complete/…)
nunca somem. Default seguro; `tools.surfaces.<surface>.{allow,deny}` no okami.yaml sobrepõe.
"""

from __future__ import annotations

from okami.core.tool_registry import spec

# Repertório que NENHUM canal remoto deve ter por padrão: shell e gestão de processo + spawn.
# (process_start/run_shell já caem pelo teto 'dangerous', mas listamos explícito p/ clareza + cobrir
#  process_write/signal/kill, que são 'sensitive' e passariam pelo teto.)
_REMOTE_DENY = {"run_shell", "process_start", "process_write", "process_signal", "process_kill", "spawn"}

# Negações default por superfície. cli = máquina do dono → surface completa.
_DENY_BY_SURFACE: dict[str, set[str]] = {
    "cli": set(),
    "telegram": set(_REMOTE_DENY),                   # remoto: nada de shell/processo/spawn por padrão
    "group": _REMOTE_DENY | {"generate_image"},      # grupo: mais restrito ainda
    "paperclip": set(),                              # governado pelo approval (defer)
    "subagent": {"spawn"},                           # subagente não spawna (anti-recursão explosiva)
    "api": set(_REMOTE_DENY),
    "cron": set(),
    "slack": set(_REMOTE_DENY),                      # #P1: canal REST remoto ≠ CLI local
    "discord": set(_REMOTE_DENY),
    "mattermost": set(_REMOTE_DENY),
}
# Teto de sensibilidade por superfície (defesa extra): remoto não roda 'dangerous' sem opt-in.
_MAX_DANGER: dict[str, str] = {"telegram": "sensitive", "group": "safe", "api": "sensitive",
                               "slack": "sensitive", "discord": "sensitive", "mattermost": "sensitive"}
_DANGER_RANK = {"safe": 0, "sensitive": 1, "dangerous": 2}

# nome do canal (channel.name) → superfície. Mais confiável que o nome da CLASSE.
_NAME_TO_SURFACE = {"telegram": "telegram", "telegram-group": "group", "slack": "slack",
                    "discord": "discord", "mattermost": "mattermost", "paperclip": "paperclip"}


def surface_of(channel) -> str:
    """Mapeia o canal → superfície. Usa channel.name (confiável) antes do nome da classe (#P1).

    Antes, Slack/Discord/Mattermost caíam no 'else' → 'cli' → ganhavam shell/processo (bug de surface)."""
    name = str(getattr(channel, "name", "") or "").lower()
    if name in _NAME_TO_SURFACE:
        return _NAME_TO_SURFACE[name]
    cls = type(channel).__name__.lower()             # fallback pela classe (compat / canais sem .name)
    for key, surface in (("group", "group"), ("telegram", "telegram"), ("paperclip", "paperclip"),
                         ("slack", "slack"), ("discord", "discord"), ("mattermost", "mattermost")):
        if key in cls:
            return surface
    return "cli"


def denied(surface: str, name: str, *, config=None) -> bool:
    """True se a tool `name` é negada na `surface` (default + override de config)."""
    s = spec(name)
    if s and s.terminal:                             # terminais de controle nunca somem
        return False
    cfg = ((config or {}).get("surfaces") or {}).get(surface) or {}
    if name in set(cfg.get("allow") or []):          # allow explícito vence
        return False
    if name in (set(_DENY_BY_SURFACE.get(surface, set())) | set(cfg.get("deny") or [])):
        return True
    cap = _MAX_DANGER.get(surface)
    if cap and s and _DANGER_RANK.get(s.danger, 0) > _DANGER_RANK[cap]:
        return True
    return False


def filter_registry(registry: dict, surface: str = "cli", *, config=None) -> dict:
    """Devolve um registro só com as tools permitidas na superfície."""
    if surface == "cli" and not (config or {}).get("surfaces"):
        return registry                              # caminho comum: nada a filtrar (sem cópia)
    return {name: tool for name, tool in registry.items()
            if not denied(surface, name, config=config)}
