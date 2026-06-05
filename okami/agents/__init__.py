"""Multi-agente (§10): profiles + workspaces isolados + roteamento por bindings.

Cada agente vive em `agents/<id>/` (= workspace isolado): `agent.yaml` (overrides sobre o
okami.yaml global) + identidade (SOUL/VOICE/PERSONA) + memória própria (`.okami/`). Assim cada
agente tem provider/memória/aprovação/persona próprios — e depois o seu próprio Telegram.

Roteamento (estilo OpenClaw/passo-11): uma origem (canal/peer) casa com um agente por bindings
com tiers de especificidade — exato > regex > wildcard; primeiro match vence; senão, o default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from okami.config import OkamiConfig, _deep_merge, build_config


@dataclass
class AgentSpec:
    id: str
    dir: Path
    raw: dict  # conteúdo do agent.yaml (overrides)


def load_agents(root: str | Path | None = None) -> dict[str, AgentSpec]:
    from okami.home import agents_dir
    root = Path(root) if root is not None else agents_dir()   # casa central (não espalha no CWD)
    out: dict[str, AgentSpec] = {}
    if not root.exists():
        return out
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        f = d / "agent.yaml"
        if f.exists():
            raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            out[d.name] = AgentSpec(d.name, d, raw)
    return out


def effective_config(global_raw: dict, spec: AgentSpec) -> OkamiConfig:
    """Config efetiva do agente = global + overrides do agent.yaml (deep-merge)."""
    return build_config(_deep_merge(global_raw, spec.raw))


def _tier(pattern: str) -> int:
    if pattern in (".*", "*"):
        return 2                       # wildcard
    return 0 if re.escape(pattern) == pattern else 1   # exato : regex


class Router:
    """Mapeia uma origem (ex.: 'telegram:12345') para um agente, por bindings."""

    def __init__(self, bindings: list[dict] | None = None, default: str | None = None):
        self.bindings = bindings or []
        self.default = default

    def route(self, source: str) -> str | None:
        best: tuple[int, str] | None = None
        for b in self.bindings:
            pat, agent = b.get("match", ""), b.get("agent")
            if not agent:
                continue
            try:
                hit = re.fullmatch(pat, source) is not None
            except re.error:
                hit = pat == source
            if hit:
                t = _tier(pat)
                if best is None or t < best[0]:
                    best = (t, agent)
        return best[1] if best else self.default


def build_router(agents_cfg: dict, agents: dict[str, AgentSpec]) -> Router:
    """Bindings = os globais (agents.bindings) + os `match` declarados por cada agente."""
    bindings = list((agents_cfg or {}).get("bindings", []))
    for aid, spec in agents.items():
        for m in (spec.raw.get("match") or []):
            bindings.append({"match": m, "agent": aid})
    return Router(bindings, default=(agents_cfg or {}).get("default"))
