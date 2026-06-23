"""Auto-aprimoramento — closed learning loop (§7), fatia 1: reflexão → memória.

Depois de cada tarefa, o harness já registrou tudo (passos + sinais: violations/loops/gate
rejections). `reflect` destila isso em LIÇÕES e ANTI-PADRÕES gravados na memória — que voltam
INJETADOS na próxima tarefa parecida (recall), fechando o loop: o agente para de repetir erros
e reusa o que funcionou. Determinístico e testável; uma camada de reflexão por LLM (mais rica)
e o auto-tune do capability profile entram em cima depois.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from okami.core import Task, TaskState
from okami.memory.base import MemoryItem

_TUNING = ".okami/tuning.json"


def reflect(task: Task, model_name: str = "?") -> list[MemoryItem]:
    """Aprende SÓ de falha COMPORTAMENTAL real — não vira post-mortem de TODA tarefa.

    Antes gravava 'COMO: para <frase> funcionou a sequência <tools>' em todo COMPLETE e um anti-padrão
    em todo BLOCKED/FAILED, ANCORADOS na frase literal do usuário. Resultado: o recall enchia de lixo
    re-descobrível que sequestrava o pedido seguinte e realimentava o erro. Alinhado ao Hermes: memória
    de longo prazo só guarda conhecimento DURÁVEL e GENERALIZÁVEL — sequência de tools é re-descobrível
    (não entra) e o sinal de qualidade por-tarefa já vai p/ task.stats → auto-tune do capability profile
    (record_run), que é o lugar certo, sem poluir o recall.

    Mantém UM anti-padrão GENERALIZADO (sem a frase literal → dedup no backend) só quando a falha tem
    sinal comportamental real: estado FAILED com ≥2 violações OU ≥1 loop. BLOCKED (timeout/cancelamento/
    need_input) é transitório → não vira memória."""
    stats = task.stats or {}
    viol = int(stats.get("violations", 0))
    loops = int(stats.get("loops", 0))
    if task.state == TaskState.FAILED and (viol >= 2 or loops >= 1):
        return [MemoryItem(
            kind="anti_pattern", source="reflection",
            text=(f"ANTI-PADRÃO ({model_name}): tarefa falhou com {viol} violações / {loops} loops. "
                  "Decompor em passos menores, verificar o resultado antes de seguir e NÃO repetir "
                  "a mesma ação que já falhou."),
        )]
    return []


def is_reflection_noise(item) -> bool:
    """True p/ memória auto-aprendida de BAIXO valor (post-mortem ancorado na frase do pedido), p/ o
    `okami memory prune`: a 'lesson' de sequência de tools (sempre lixo agora) e o anti-padrão ANTIGO
    phrase-anchored ('… terminou BLOCKED/FAILED …'). O anti-padrão NOVO generalizado é preservado."""
    kind = getattr(item, "kind", "") or ""
    text = getattr(item, "text", "") or ""
    if kind == "lesson" and text.startswith("COMO:"):
        return True
    return kind == "anti_pattern" and "terminou " in text


def apply(memory, task: Task, model_name: str = "?") -> list[MemoryItem]:
    """Reflete e GRAVA as lições na memória (defensivo: nunca derruba o fluxo). Passa pelo policy.prepare
    (gate Do-NOT-capture + classificação) — defesa em profundidade: nem a reflexão escapa do filtro."""
    from okami.memory.policy import prepare
    lessons = reflect(task, model_name)
    if memory is not None:
        for lesson in lessons:
            try:
                item = prepare(lesson.text, source=lesson.source or "reflection", kind=lesson.kind)
                if item is not None:
                    memory.write(item)
            except Exception as e:  # noqa: BLE001 — uma lição que não grava NÃO derruba o turno, mas registra
                from okami import log                       # (era silêncio total: memória podia falhar 100%
                log.warn(f"learning: lição não persistida ({e}).")   # sem nenhum sinal — falha invisível)
    return lessons


# ----------------------------------------------------- AUTO-SKILL (Fase 5, estilo Hermes "skill from experience")
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def _skill_name(text: str, *, tools: list[str] | None = None) -> str:
    """Nome de skill CURTO e bom (kebab-case, ≤3 palavras): delega ao core.naming.short_name —
    tira acento, remove filler conversacional, descarta verbo genérico p/ ficar no tópico."""
    from okami.core.naming import short_name
    return short_name(text, tools=tools, fallback="skill")


# tools que NÃO contam como "trabalho" ao decidir destilar skill (terminais + meta).
_META_TOOLS = {"task_complete", "task_blocked", "need_input", "respond", "use_skill", "finish_setup"}
# assinatura do corpo auto-distilado determinístico — usada p/ podar o lixo já existente.
AUTO_BODY_MARKER = "(sequência de tools que funcionou)"


def is_auto_distilled(skill) -> bool:
    """True se a skill foi gerada pelo auto_skill (p/ `okami skills --prune`). Sinais, em ordem:
    marcador `origin: auto-distilled` (skills novas) OU a ASSINATURA do corpo — determinístico
    ('(sequência de tools que funcionou)') ou por LLM ('## Quando usar' + '## Cuidados'). Nenhum
    desses padrões aparece em skill CURADA do repo (verificado), então não há falso-positivo."""
    origin = str((skill.meta or {}).get("origin", ""))
    if origin == "auto-distilled":
        return True
    if origin:                                   # origin EXPLÍCITO ≠ auto (ex.: 'agent' via manage_skill/review)
        return False                             # → curada; heurística de corpo não pode comê-la
    body = skill.body or ""
    if AUTO_BODY_MARKER in body:
        return True
    return "## Quando usar" in body and "## Cuidados" in body


def _is_distillable(task: Task) -> bool:
    """Só vira SKILL a tarefa que MERECE um procedimento reusável: CONCLUÍDA e com EFEITO durável real
    (≥4 passos de tool, ≥2 tools distintas, ≥2 com efeito). O gate de EFEITO é a chave: papo e
    exploração read-only (ls/grep/cat/read_file → effect=False) NÃO viram skill — era a fábrica de lixo
    ('pasta-okami-agent', 'deveria-intelignete-sabe' ancorado na frase literal do usuário, que depois
    sequestrava o pedido seguinte e realimentava o erro)."""
    if task.state != TaskState.COMPLETE:
        return False
    real = [s for s in task.steps if s.tool not in _META_TOOLS]
    effectful = [s for s in real if getattr(s, "effect", False)]
    return len(real) >= 4 and len({s.tool for s in real}) >= 2 and len(effectful) >= 2


def validate_distilled(sk: dict, goal: str) -> str | None:
    """Gate DETERMINÍSTICO anti-lixo (objeção ou None) — barra skill ruim mesmo se o LLM escorregar.

    Reproduz os 4 modos de falha reais ('tu-fez-cagada', 'sou-marcos-santos'…): nome copiado do começo
    da frase do pedido, descrição = frase crua, corpo-transcript (conversa verbatim) e corpo raso
    (setas de tools não são procedimento). Hermes valida deterministicamente em cima do LLM — igual aqui."""
    import unicodedata

    def _norm(s: str) -> str:
        return unicodedata.normalize("NFKD", str(s).lower()).encode("ascii", "ignore").decode()

    name = str(sk.get("name") or "")
    desc = str(sk.get("description") or "")
    body = str(sk.get("body") or "")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+){1,3}", name) or len(name) > 32:
        return "nome fora do padrão (kebab-case, 2-4 palavras, ≤32 chars)"
    # padrão real do lixo ('tu-fez-cagada', 'sou-marcos-santos'): nome = trecho CONSECUTIVO do começo
    # da frase. ≥3 palavras seguidas é cópia, não tópico (2 palavras tipo 'deploy-docker' são legítimas).
    gtoks = re.findall(r"[a-z0-9]+", _norm(goal))
    if len(name.split("-")) >= 3 and " ".join(name.split("-")) in " ".join(gtoks[:10]):
        return "nome copiado do começo da frase do pedido (artefato de sessão, não classe)"
    if not 20 <= len(desc) <= 200:
        return "descrição ausente/curta/longa (alvo: 'Use quando <gatilho>. <comportamento>.')"
    if _norm(desc)[:40] == _norm(goal)[:40]:
        return "descrição é a frase crua do pedido"
    if len(body) < 200 or "## " not in body:
        return "corpo raso/sem seções — sequência de tools não é procedimento"
    g, b = _norm(goal), _norm(body)
    if len(g) >= 60 and any(g[i:i + 60] in b for i in range(0, len(g) - 59, 20)):
        return "corpo contém a conversa verbatim (transcript, não procedimento)"
    return None


# Prompt alinhado ao Hermes (skill-authoring + background_review): skill = CLASSE de trabalho,
# descrição "Use quando <gatilho>", corpo com seções, e o direito de dizer NÃO (worth=false).
_DISTILL_SYSTEM = """Você decide se uma tarefa concluída merece virar uma SKILL reutilizável — e, SÓ se merecer, escreve a skill. "NÃO vale" é o resultado mais comum e é legítimo: melhor nenhuma skill do que lixo.

worth=false quando: tarefa pontual/one-off ("organize ISSO", "corrige ESSE erro"), papo/correção conversacional, apresentação pessoal, narrativa de uma sessão. worth=true SÓ quando emergiu um PROCEDIMENTO de uma CLASSE de trabalho que vai se repetir com outros dados.

Se worth=true:
- name: a CLASSE em kebab-case, 2-4 palavras (ex.: 'organizar-arvore-pastas', 'deploy-docker'). NUNCA frase do pedido, número de PR, erro ou codinome da sessão.
- description: "Use quando <gatilho observável>. <o que a skill faz em 1 linha>." (≤160 chars, 3ª pessoa)
- intent_examples: 2-3 PARÁFRASES genéricas de pedidos que deveriam acionar a skill (não a frase original).
- body: markdown com '## Quando usar' (incl. "Não use para: …"), '## Procedimento' (passos numerados, genéricos, com as tools certas), '## Cuidados' (armadilhas reais vistas na tarefa). Genérico: outros dados, mesmos passos. PROIBIDO colar a conversa, o resultado literal ou tom de chat ("Pronto!")."""


def distill_skill_llm(cfg, task: Task, provider: str | None = None) -> dict | None:
    """Destila uma SKILL.md via LLM com julgamento 'vale salvar?' + gate determinístico.
    SEM fallback mecânico: LLM indisponível/falhou/worth=false/gate reprovou → None (nada gravado)."""
    if cfg is None or not _is_distillable(task):
        return None
    from okami.llm import providers as prov

    seq = " → ".join(s.tool for s in task.steps if s.tool not in _META_TOOLS)
    schema = {"type": "object", "properties": {
        "worth": {"type": "boolean"}, "name": {"type": "string"}, "description": {"type": "string"},
        "intent_examples": {"type": "array", "items": {"type": "string"}}, "body": {"type": "string"}},
        "required": ["worth", "name", "description", "body"]}
    msgs = [{"role": "system", "content": _DISTILL_SYSTEM},
            {"role": "user", "content": f"PEDIDO: {task.goal[:800]}\nAÇÕES (tools): {seq}\n"
             f"RESULTADO (não copie p/ a skill): {(task.result or '')[:300]}"}]
    if provider is None:                          # fundo → modelo AUXILIAR barato se configurado
        from okami.llm.aux import aux_for
        provider, aux_model = aux_for(cfg, "distill")
    else:
        aux_model = None
    try:
        d = json.loads(prov.complete_messages(cfg, msgs, provider=provider, model=aux_model,
                                              response_schema=schema))
    except Exception:  # noqa: BLE001
        return None
    if not d.get("worth"):
        return None
    sk = {"name": str(d.get("name") or "").strip(),
          "description": str(d.get("description") or "").strip(),
          "intent_examples": [str(x).strip() for x in (d.get("intent_examples") or []) if str(x).strip()][:3],
          "body": str(d.get("body") or "").strip()}
    return None if validate_distilled(sk, task.goal or "") else sk


def _render_skill_md(sk: dict, task: Task) -> str:
    """Empacota a skill destilada com frontmatter LIMPO: description do LLM ("Use quando…"),
    intent_examples = paráfrases GENERALIZADAS do LLM + a frase real do pedido como última âncora
    (achável por intenção sem sujar a descrição). Se o distilador já trouxe frontmatter, respeita."""
    import yaml

    body = (sk.get("body") or "").strip()
    if body.startswith("---"):
        return body + "\n"
    goal = (task.goal or "").strip()
    examples = list(sk.get("intent_examples") or [])
    if goal and goal[:200] not in examples:
        examples.append(goal[:200])                       # âncora de retrieval, nunca a descrição
    meta = {
        "name": sk["name"],
        "description": str(sk.get("description") or "")[:160],
        "intent_examples": examples[:4],
        "origin": "auto-distilled",                        # marcado → `okami skills prune` poda com precisão
    }
    return "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + body + "\n"


def maybe_write_skill(task: Task, skills_dir: str = "skills", model_name: str = "?", cfg=None) -> str | None:
    """Destila via LLM (julgamento + gate) → ESCANEIA o documento INTEIRO (segurança) → grava em
    skills/<name>/SKILL.md. SEM fallback mecânico: sem cfg/LLM → None (nada gravado). Devolve nome/None."""
    from okami.skills.skill_security import Severity, scan_text

    sk = distill_skill_llm(cfg, task)
    if not sk:
        return None
    rendered = _render_skill_md(sk, task)                 # escaneia o doc final (inclui intent_examples)
    if any(f.severity >= Severity.HIGH for f in scan_text(sk["name"], rendered)):
        return None                                       # nunca ativa skill insegura (defesa em profundidade)
    f = Path(skills_dir) / sk["name"] / "SKILL.md"
    if f.exists():
        return None                                       # não sobrescreve skill existente
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(rendered, encoding="utf-8", newline="\n")
    return sk["name"]


# ----------------------------------------------------- AUTO-TUNE do capability profile por modelo (§3.5/§7)
def record_run(workspace, model: str, stats: dict) -> dict:
    """Acumula sinais por MODELO (violations/loops/rejections) p/ calibrar o capability profile."""
    p = Path(workspace) / _TUNING
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    m = data.setdefault(model, {"runs": 0, "violations": 0, "loops": 0, "gate_rejections": 0})
    m["runs"] += 1
    for k in ("violations", "loops", "gate_rejections"):
        m[k] += int((stats or {}).get(k, 0))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
    return m


def tuned_overrides(workspace, model: str) -> dict:
    """Recomenda ajustes com base no histórico do modelo. Hoje: muita ação malformada (violations/run
    alto) → forçar `json_constrained` (constrained decoding) p/ aquele modelo. §3.5."""
    p = Path(workspace) / _TUNING
    if not p.exists():
        return {}
    try:
        m = json.loads(p.read_text(encoding="utf-8")).get(model)
    except (json.JSONDecodeError, OSError):
        return {}
    if not m or m["runs"] < 3:                       # amostra mínima 3 + exige 100% de violação (abaixo):
        return {}                                     # adapta RÁPIDO modelo local fraco a json_constrained
    if m["violations"] / max(1, m["runs"]) >= 1.0:
        return {"tool_mode": "json_constrained"}
    return {}
