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


def _isolation_override(sandbox, cfg_surface) -> bool:
    """Só uma flag GROTESCAMENTE explícita libera shell/processo sem isolamento real (#P1).

    `tools.surfaces.<s>.allow` comum NÃO fura o gate — abrir execução sem isolamento exige uma
    declaração que ninguém liga por acidente: `sandbox.unsafe_allow_host_shell_without_isolation: true`
    (deploy inteiro) ou `tools.surfaces.<s>.unsafe_allow_without_isolation: true` (por superfície)."""
    sb = sandbox if isinstance(sandbox, dict) else {}
    return bool(sb.get("unsafe_allow_host_shell_without_isolation")
                or (cfg_surface or {}).get("unsafe_allow_without_isolation"))


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
    # #P1: gate de isolamento PRIMEIRO — worker Paperclip remoto só EXECUTA shell/processo com isolamento
    # real. `allow` comum NÃO fura isto (era o buraco); só a flag unsafe_* grotesca libera (ver _isolation_override).
    if surface in _PAPERCLIP_EXEC_SURFACES and name in _EXEC_TOOLS and not _sandbox_isolated(sandbox):
        if not _isolation_override(sandbox, cfg):
            return True
    if name in set(cfg.get("allow") or []):          # allow vence o DENYLIST normal (mas não o gate acima)
        return False
    if name in (set(_DENY_BY_SURFACE.get(surface, set())) | set(cfg.get("deny") or [])):
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


# ── filtro de tools MCP por SUPERFÍCIE (#P1) ───────────────────────────────────
# As tools MCP entram no registro DEPOIS do filter_registry (são carregadas em runtime) → sem isto
# elas escapavam da policy por superfície. Pior: rodam em processo SEPARADO → uma tool MCP com
# capability shell/write FURA o sandbox do worker. Aqui aplicamos a MESMA postura: máquina do dono
# (cli/cron/subagent) recebe MCP livre; superfície remota só recebe MCP de EFEITO COLATERAL
# (write/shell/network/secret-access) se o deploy ABRIR por nome (tools.surfaces.<s>.allow); worker
# Paperclip só recebe MCP perigoso COM isolamento real.
_MCP_OWNER_SURFACES = frozenset({"cli", "cron", "subagent"})


def mcp_denied(tool, surface: str, *, config=None, sandbox=None) -> bool:
    """True se a tool MCP `tool` deve ser REMOVIDA na `surface` (capability × postura da superfície)."""
    from okami.integrations.mcp import DANGEROUS_CAPS
    name = getattr(tool, "name", "")
    cfg = ((config or {}).get("surfaces") or {}).get(surface) or {}
    danger = set(getattr(tool, "capabilities", set()) or set()) & DANGEROUS_CAPS
    # #P1: gate de isolamento ANTES do allow — uma tool MCP de EFEITO (shell/write/network) num worker
    # Paperclip remoto roda em processo SEPARADO → FURA o sandbox. `allow` comum NÃO libera isso (era o
    # buraco); só a flag grotesca (unsafe_allow_*_without_isolation), igual ao gate das tools nativas.
    if danger and surface in _PAPERCLIP_EXEC_SURFACES and not _sandbox_isolated(sandbox):
        if not _isolation_override(sandbox, cfg):
            return True
    if name in set(cfg.get("allow") or []):          # allow vence o resto (mas NÃO o gate de isolamento acima)
        return False
    if name in set(cfg.get("deny") or []):
        return True
    if surface in _MCP_OWNER_SURFACES:               # máquina do dono → MCP livre
        return False
    if not danger:
        return False                                 # MCP só-leitura passa em QUALQUER superfície
    if surface in _PAPERCLIP_EXEC_SURFACES:          # worker isolado (passou o gate acima) → permitido
        return False
    return True                                      # demais superfícies remotas: nada de efeito via MCP sem allow


def filter_mcp_registry(mcp_tools: dict, surface: str = "cli", *, config=None, sandbox=None,
                        emit=lambda m: None) -> dict:
    """Filtra as tools MCP pela postura da superfície; avisa o que removeu (auditável)."""
    if surface in _MCP_OWNER_SURFACES and not (config or {}).get("surfaces"):
        return mcp_tools                             # caminho comum: nada a filtrar
    kept, dropped = {}, []
    for name, tool in mcp_tools.items():
        if mcp_denied(tool, surface, config=config, sandbox=sandbox):
            dropped.append(name)
        else:
            kept[name] = tool
    if dropped:
        emit(f"🛡  MCP filtrado na superfície '{surface}': {len(dropped)} tool(s) de efeito colateral "
             f"removida(s) ({', '.join(dropped[:5])}{'…' if len(dropped) > 5 else ''}) — "
             f"abra por deploy com tools.surfaces.{surface}.allow se preciso.")
    return kept
