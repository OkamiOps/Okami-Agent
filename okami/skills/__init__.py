"""Runtime de skills (§4.2) — formato agentskills.io (SKILL.md) + router.

Router força a skill relevante no contexto: para tarefas de frontend cobertas por um
contrato de UI, a skill `frontend-<library>` é OBRIGATÓRIA. O harness injeta o corpo da
skill no system prompt; o gate (§4.3) verifica o resultado. Skill é gate, não sugestão.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

FRONTEND_KEYWORDS = {
    "frontend", "front-end", "ui", "interface", "component", "componente", "page",
    "página", "pagina", "tela", "dashboard", "landing", "form", "formulário",
    "app", "tailwind", "react", "next", "site", "web",
}

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    triggers: list[str]
    meta: dict
    body: str
    path: Path


def parse_skill(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER.match(text)
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        body = m.group(2).strip()
    else:
        meta, body = {}, text.strip()
    return Skill(
        name=meta.get("name") or path.parent.name,
        description=meta.get("description", ""),
        triggers=[str(t).lower() for t in (meta.get("triggers") or [])],
        meta=meta,
        body=body,
        path=path,
    )


def load_skills(root: Path) -> list[Skill]:
    if not root.exists():
        return []
    return [parse_skill(p) for p in sorted(root.rglob("SKILL.md"))]


def route(goal: str, contracts: dict, skills: list[Skill]) -> list[Skill]:
    """Skills OBRIGATÓRIAS (injetadas inteiras) — só as exigidas por contrato.

    O resto vai para o catálogo (progressive disclosure via `use_skill`), evitando inflar o
    prompt. Triggers servem para ranquear o catálogo, não para forçar injeção.
    """
    g = goal.lower()
    by_name = {s.name: s for s in skills}
    forced: list[Skill] = []
    lib = ((contracts or {}).get("ui") or {}).get("library")
    if lib and any(k in g for k in FRONTEND_KEYWORDS):
        sk = by_name.get(f"frontend-{lib}")
        if sk:
            forced.append(sk)
    return forced


def render_block(skills: list[Skill]) -> str:
    if not skills:
        return ""
    parts = ["SKILLS OBRIGATÓRIAS para esta tarefa (siga à risca, não improvise):"]
    for s in skills:
        parts.append(f"\n### skill: {s.name}\n{s.body}")
    return "\n".join(parts)


def catalog(skills: list[Skill], exclude: set[str] | None = None) -> str:
    """Catálogo leve (nome + descrição) das skills disponíveis — progressive disclosure.
    O agente carrega a relevante com a tool `use_skill` (estilo Claude Code)."""
    exclude = exclude or set()
    items = [s for s in skills if s.name not in exclude]
    if not items:
        return ""
    lines = ["SKILLS DISPONÍVEIS (carregue a relevante com a tool `use_skill`):"]
    lines += [f"- {s.name}: {s.description[:120]}" for s in items]
    return "\n".join(lines)
