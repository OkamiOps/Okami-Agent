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
# Worker (Paperclip): EXECUTA (run_shell/process_start sob sandbox+defer), mas não GERENCIA processo
# de terceiro nem recursiona (process_write/signal/kill, spawn fora). #P1.
_WORKER_DENY = {"process_write", "process_signal", "process_kill", "spawn"}

# Negações default por superfície. cli = máquina do dono → surface completa.
_DENY_BY_SURFACE: dict[str, set[str]] = {
    "cli": set(),
    "telegram": set(_REMOTE_DENY),                   # remoto: nada de shell/processo/spawn por padrão
    "group": _REMOTE_DENY | {"generate_image"},      # grupo: mais restrito ainda
    "subagent": {"spawn"},                           # subagente não spawna (anti-recursão explosiva)
    "api": set(_REMOTE_DENY),
    "cron": set(),
    "slack": set(_REMOTE_DENY),                      # #P1: canal REST remoto ≠ CLI local
    "discord": set(_REMOTE_DENY),
    "mattermost": set(_REMOTE_DENY),
    # Paperclip POR PAPEL (#P1): antes 'paperclip' era surface COMPLETA (porta larga). Agora o default
    # já é o worker (executa, mas não gerencia processo/recursiona), e cada papel tem repertório próprio.
    "paperclip": set(_WORKER_DENY),                  # default = worker
    "paperclip-worker": set(_WORKER_DENY),           # executa sob sandbox + governança defer
    "paperclip-manager": set(_REMOTE_DENY),          # control plane: orquestra, NÃO executa shell/processo
    "paperclip-reviewer": _REMOTE_DENY | {"write_file", "edit_file"},  # revisa/lê, não executa nem escreve
    "paperclip-external": set(_REMOTE_DENY),         # externo não-confiável: nada perigoso (+ cap safe abaixo)
}
# Teto de sensibilidade por superfície (defesa extra): remoto não roda 'dangerous' sem opt-in.
_MAX_DANGER: dict[str, str] = {"telegram": "sensitive", "group": "safe", "api": "sensitive",
                               "slack": "sensitive", "discord": "sensitive", "mattermost": "sensitive",
                               "paperclip-manager": "sensitive", "paperclip-reviewer": "safe",
                               "paperclip-external": "safe"}
_DANGER_RANK = {"safe": 0, "sensitive": 1, "dangerous": 2}

# Papel do Paperclip (me['role'] do control plane) → superfície. Default = worker (papel desconhecido).
_PAPERCLIP_ROLE_SURFACE = {"worker": "paperclip-worker", "manager": "paperclip-manager",
                           "reviewer": "paperclip-reviewer", "external": "paperclip-external",
                           "admin": "paperclip-manager", "orchestrator": "paperclip-manager"}

# Gate de isolamento (#P1, opcional-por-default mas FAIL-CLOSED no worker remoto): um worker Paperclip
# que EXECUTA shell/processo num control plane remoto só faz isso COM isolamento real (Docker/require_
# isolation). Sem isolamento, run_shell/process_start ficam fechados — a não ser que o deploy ABRA
# explícito via tools.surfaces.paperclip.allow. Não muda o default de DEV (CLI local nunca é gated).
_EXEC_TOOLS = frozenset({"run_shell", "process_start"})
_PAPERCLIP_EXEC_SURFACES = frozenset({"paperclip", "paperclip-worker"})


def _sandbox_isolated(sandbox) -> bool:
    """True se o sandbox dá isolamento REAL: Docker exigido (require_isolation) ou backend → docker."""
    if not sandbox:
        return False
    from okami.core.sandbox import SandboxPolicy
    p = SandboxPolicy.from_config(sandbox if isinstance(sandbox, dict) else {})
    return bool(p.require_isolation) or p.effective_backend() == "docker"


def paperclip_surface(role) -> str:
    """Papel do Paperclip → superfície de tool policy (#P1). Papel desconhecido → 'paperclip' (worker)."""
    return _PAPERCLIP_ROLE_SURFACE.get(str(role or "").lower().strip(), "paperclip")


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


def denied(surface: str, name: str, *, config=None, sandbox=None) -> bool:
    """True se a tool `name` é negada na `surface` (default + override de config + gate de isolamento)."""
    s = spec(name)
    if s and s.terminal:                             # terminais de controle nunca somem
        return False
    cfg = ((config or {}).get("surfaces") or {}).get(surface) or {}
    if name in set(cfg.get("allow") or []):          # allow explícito vence (inclui o gate de isolamento)
        return False
    if name in (set(_DENY_BY_SURFACE.get(surface, set())) | set(cfg.get("deny") or [])):
        return True
    # #P1: worker Paperclip remoto só EXECUTA shell/processo com isolamento real (ou allow explícito acima).
    if surface in _PAPERCLIP_EXEC_SURFACES and name in _EXEC_TOOLS and not _sandbox_isolated(sandbox):
        return True
    cap = _MAX_DANGER.get(surface)
    if cap and s and _DANGER_RANK.get(s.danger, 0) > _DANGER_RANK[cap]:
        return True
    return False


def filter_registry(registry: dict, surface: str = "cli", *, config=None, sandbox=None) -> dict:
    """Devolve um registro só com as tools permitidas na superfície (`sandbox` ativa o gate #P1)."""
    if surface == "cli" and not (config or {}).get("surfaces"):
        return registry                              # caminho comum (máquina do dono): nada a filtrar
    return {name: tool for name, tool in registry.items()
            if not denied(surface, name, config=config, sandbox=sandbox)}
