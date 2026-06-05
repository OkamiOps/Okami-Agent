"""Tool policy POR SUPERFÍCIE/agente (P1.4) — a mesma tool surface NÃO serve pra tudo.

OpenClaw resolve policy por superfície (CLI local, Telegram, grupo, subagente, Paperclip…). Aqui o
registro de tools (#14) é FILTRADO por superfície: Telegram não roda shell por padrão, grupo é ainda
mais restrito, subagente não dá `spawn` (anti-recursão). As tools TERMINAIS (respond/task_complete/…)
nunca somem. Default seguro; `tools.surfaces.<surface>.{allow,deny}` no okami.yaml sobrepõe.
"""

from __future__ import annotations

from okami.core.tool_registry import spec

# Negações default por superfície. cli = máquina do dono → surface completa.
_DENY_BY_SURFACE: dict[str, set[str]] = {
    "cli": set(),
    "telegram": {"run_shell"},                       # remoto: nada de shell por padrão
    "group": {"run_shell", "spawn", "generate_image"},  # grupo: mais restrito ainda
    "paperclip": set(),                              # governado pelo approval (defer)
    "subagent": {"spawn"},                           # subagente não spawna (anti-recursão explosiva)
    "api": {"run_shell"},
    "cron": set(),
}
# Teto de sensibilidade por superfície (defesa extra): remoto não roda 'dangerous' sem opt-in.
_MAX_DANGER: dict[str, str] = {"telegram": "sensitive", "group": "safe", "api": "sensitive"}
_DANGER_RANK = {"safe": 0, "sensitive": 1, "dangerous": 2}


def surface_of(channel) -> str:
    """Mapeia o canal → superfície (pela classe). Default 'cli'."""
    cls = type(channel).__name__.lower()
    if "group" in cls:
        return "group"
    if "telegram" in cls:
        return "telegram"
    if "paperclip" in cls:
        return "paperclip"
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
