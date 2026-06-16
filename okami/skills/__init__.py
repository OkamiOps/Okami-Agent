"""Runtime de skills (§4.2) — formato agentskills.io (SKILL.md) + router.

Router força a skill relevante no contexto: para tarefas de frontend cobertas por um
contrato de UI, a skill `frontend-<library>` é OBRIGATÓRIA. O harness injeta o corpo da
skill no system prompt; o gate (§4.3) verifica o resultado. Skill é gate, não sugestão.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FRONTEND_KEYWORDS = {
    "frontend", "front-end", "ui", "interface", "component", "componente", "page",
    "página", "pagina", "tela", "dashboard", "landing", "form", "formulário",
    "app", "tailwind", "react", "next", "site", "web",
}

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)

# Pedido sobre o PRÓPRIO Okami → o harness força a skill de auto-referência `okami-agent`
# (capacidades · tools · comandos · providers · harness · segurança). Conservador DE PROPÓSITO: só
# dispara quando o pedido é claramente META — senão inflaria o prompt de QUALQUER task que cite 'okami'.
SELF_DOC_SKILL = "okami-agent"
# Frases que, por si só (mesmo sem 'okami'), já são uma pergunta sobre o agente:
_SELF_PHRASES = (
    "okami-agent", "okami agent",
    "what can you do", "what can okami do", "what are your capabilities", "your capabilities",
    "okami's capabilities", "how do you work", "how does okami work",
    "what tools do you", "which tools do you", "list your commands", "which commands do you",
    "o que você consegue fazer", "o que voce consegue fazer", "o que o okami faz",
    "quais suas capacidades", "quais são suas capacidades", "quais sao suas capacidades",
    "capacidades do okami", "como você funciona", "como voce funciona", "como o okami funciona",
    "quais comandos", "que comandos", "quais ferramentas", "que ferramentas você", "que ferramentas voce",
)
# Palavras-meta que SÓ forçam quando 'okami' também aparece (evita disparar em task de dev comum):
_SELF_META_KW = (
    "capabilit", "capacidade", "/model", "/think", "provider", "gateway", "harness",
    "fallback", "exit criteri", "critério de saída", "criterio de saida", "readiness", "slash command",
)


def is_self_query(goal: str) -> bool:
    """True se o pedido é sobre o PRÓPRIO Okami — aí vale forçar a skill `okami-agent` no contexto."""
    g = (goal or "").lower()
    if any(p in g for p in _SELF_PHRASES):
        return True
    return "okami" in g and any(k in g for k in _SELF_META_KW)


@dataclass
class Skill:
    name: str
    description: str
    triggers: list[str]
    meta: dict
    body: str
    path: Path
    intent_examples: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)      # nomes antigos (migração) → use_skill ainda resolve


def parse_skill(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER.match(text)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:               # frontmatter malformado NÃO derruba load_skills inteiro
            meta = {}
        if not isinstance(meta, dict):       # frontmatter que é escalar/lista (ex.: só "- x") → ignora
            meta = {}
        body = m.group(2).strip()
    else:
        meta, body = {}, text.strip()
    return Skill(
        name=meta.get("name") or path.parent.name,
        description=meta.get("description", ""),
        triggers=[str(t).lower() for t in (meta.get("triggers") or [])],
        # frases reais de pedido ("amor, analisa o okami-agent de novo") → casam por INTENÇÃO, não literal.
        intent_examples=[str(x) for x in (meta.get("intent_examples") or [])],
        aliases=[str(a) for a in (meta.get("aliases") or [])],
        meta=meta,
        body=body,
        path=path,
    )


def _name_is_bad(name: str) -> bool:
    """Nome RUIM = frase literal gigante OU com filler conversacional (resíduo de auto-distill antigo).
    Bom = curto, enxuto e estável sob o canonicalizador (short_name não o encurtaria)."""
    from okami.core.naming import short_name
    if len(name) > 28 or name.count("-") > 3:
        return True
    canon = short_name(name.replace("-", " "), fallback=name)
    return canon != name and len(canon) < len(name)      # canonicalizar ENCURTA → tinha filler ('amor-…')


def tidy_skill_names(root: Path, *, emit=lambda m: None) -> list[tuple[str, str]]:
    """Migra skills de nome RUIM (longo/literal, geralmente sem frontmatter) p/ o nome canônico CURTO,
    pra o catálogo parar de mostrar 'amor-eu-fiz-mudancas-...'. Reescreve o frontmatter (name canônico +
    alias antigo + description) e renomeia a pasta. Idempotente; não toca em nomes já bons."""
    import yaml as _yaml

    from okami.core.naming import short_name
    root = Path(root)
    if not root.exists():
        return []
    renamed: list[tuple[str, str]] = []
    for md in sorted(root.rglob("SKILL.md")):
        d = md.parent
        old = d.name
        if not _name_is_bad(old):
            continue
        sk = parse_skill(md)
        title = old.replace("-", " ")
        first = sk.body.splitlines()[0] if sk.body else ""
        if first.startswith("# "):
            title = first[2:].strip() or title
        canon = short_name(title, fallback="skill")
        if not canon or canon == old or _name_is_bad(canon):
            continue
        n, i = canon, 2
        while (root / n).exists():                        # colisão → sufixo
            n = f"{canon}-{i}"
            i += 1
        meta = dict(sk.meta or {})
        meta["name"] = n
        meta["aliases"] = list(dict.fromkeys([*sk.aliases, old]))
        meta.setdefault("description", (sk.description or title)[:120])
        try:
            md.write_text("---\n" + _yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
                          + "---\n" + sk.body.rstrip() + "\n", encoding="utf-8", newline="\n")
            d.rename(root / n)
            renamed.append((old, n))
            emit(f"🏷  skill renomeada: {old[:40]} → {n}")
        except OSError:
            pass
    return renamed


def load_skills(root: Path) -> list[Skill]:
    if not root.exists():
        return []
    # pula dirs ocultos (.archive do curator, .snapshots, .git…) — skill arquivada NÃO volta ao catálogo.
    return [parse_skill(p) for p in sorted(root.rglob("SKILL.md"))
            if not any(part.startswith(".") for part in p.relative_to(root).parts)]


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
    # Auto-documentação: pedido sobre o PRÓPRIO Okami → injeta a `okami-agent` inteira (não só catálogo),
    # pro agente saber exatamente suas capacidades sem depender de lembrar de chamar use_skill.
    self_sk = by_name.get(SELF_DOC_SKILL)
    if self_sk and self_sk not in forced and is_self_query(goal):
        forced.append(self_sk)
    return forced


def render_block(skills: list[Skill]) -> str:
    if not skills:
        return ""
    parts = ["SKILLS OBRIGATÓRIAS para esta tarefa (siga à risca, não improvise):"]
    for s in skills:
        parts.append(f"\n### skill: {s.name}\n{s.body}")
    return "\n".join(parts)


# piso de similaridade p/ marcar uma skill como "provável" (HRR é unit-norm → relacionado fica claramente > 0).
_PROVAVEL = 0.08


def skill_query_text(skill: Skill) -> str:
    """Superfície de INTENÇÃO da skill — o que deve casar com o pedido do usuário: nome legível +
    descrição + triggers + intent_examples. É isto que comparamos, não só o nome literal."""
    parts = [skill.name.replace("-", " ").replace("_", " "), skill.description]
    parts += list(skill.triggers) + list(skill.intent_examples)
    return "  ".join(p for p in parts if p).strip()


def _rank(embedder, goal: str, items: list[Skill]) -> list[tuple[Skill, float]]:
    import numpy as np

    enc = embedder
    if enc is None:                                  # sem embedder remoto → HRR LOCAL (offline, determinístico)
        from okami.memory.holographic import HRREncoder
        enc = HRREncoder()
    gv = np.asarray(enc.embed_one(goal), dtype=float)
    gn = float(np.linalg.norm(gv)) or 1.0
    out: list[tuple[Skill, float]] = []
    for s in items:
        sv = np.asarray(enc.embed_one(skill_query_text(s)), dtype=float)
        sn = float(np.linalg.norm(sv)) or 1.0
        sim = float(gv @ sv) / (gn * sn) if gv.shape == sv.shape and gv.size else 0.0
        out.append((s, max(0.0, sim)))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def rank_skills(goal: str, skills: list[Skill], embedder=None) -> list[tuple[Skill, float]]:
    """Ordena as skills por similaridade de INTENÇÃO ao `goal`. Usa o embedder (LMStudio) se vier;
    senão cai no HRR LOCAL — o mesmo encoder que já roda na memória. Assim o agente acha a skill por
    SIGNIFICADO (frase não-literal), não só por nome. Retorna [(skill, score≥0), …] desc."""
    items = list(skills)
    g = (goal or "").strip()
    if not items or not g:
        return [(s, 0.0) for s in items]
    try:
        return _rank(embedder, g, items)
    except Exception:  # noqa: BLE001 — embedder remoto caiu (circuit breaker) → HRR local nunca falha
        from okami.memory.holographic import HRREncoder
        return _rank(HRREncoder(), g, items)


def catalog(skills: list[Skill], exclude: set[str] | None = None, *, goal: str = "", embedder=None) -> str:
    """Catálogo leve (nome + descrição) das skills disponíveis — progressive disclosure.
    O agente carrega a relevante com a tool `use_skill` (estilo Claude Code).

    Com `goal`, ORDENA por relevância de intenção (HRR/embedder) e marca as prováveis com ⭐ — é o que
    faz a skill certa subir mesmo quando o pedido não usa a palavra literal do nome."""
    exclude = exclude or set()
    items = [s for s in skills if s.name not in exclude]
    if not items:
        return ""
    if (goal or "").strip():
        ranked = rank_skills(goal, items, embedder)
        top = ranked[0][1] if ranked else 0.0
        lines = ["SKILLS DISPONÍVEIS (ordenadas por relevância ao pedido — carregue a relevante com "
                 "`use_skill`; ⭐ = provável):"]
        for s, score in ranked:
            star = " ⭐" if score >= _PROVAVEL and score >= 0.5 * top else ""
            lines.append(f"- {s.name}: {s.description[:120]}{star}")
        return "\n".join(lines)
    lines = ["SKILLS DISPONÍVEIS (carregue a relevante com a tool `use_skill`):"]
    lines += [f"- {s.name}: {s.description[:120]}" for s in items]
    return "\n".join(lines)
