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
            except Exception:  # noqa: BLE001
                pass
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
    if str((skill.meta or {}).get("origin", "")) == "auto-distilled":
        return True
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


def distill_skill(task: Task, model_name: str = "?") -> dict | None:
    """Destila uma SKILL.md de uma tarefa BEM-sucedida e NÃO-trivial (≥4 passos, ≥2 tools distintas).
    Devolve {name, body} ou None. Determinístico (a versão por LLM entra depois)."""
    if not _is_distillable(task):
        return None
    tools = [s.tool for s in task.steps if s.tool not in _META_TOOLS]
    name = _skill_name(task.goal, tools=tools)             # nome CURTO de conteúdo, não a frase literal
    if not name:
        return None
    seq = " → ".join(tools)
    body = (f"# {task.goal[:60]}\n\n"
            f"## Quando usar\nTarefas do tipo: {task.goal[:200]}\n\n"
            f"## Como (sequência de tools que funcionou)\n{seq}\n\n"
            f"## Resultado esperado\n{(task.result or '')[:300]}\n")
    return {"name": name, "body": body}


def distill_skill_llm(cfg, task: Task, provider: str | None = None) -> dict | None:
    """Destila uma SKILL.md RICA via LLM (constrained): Quando usar / Como / Cuidados. Fallback p/ a
    versão determinística se o LLM falhar. cfg=None → pula direto p/ o determinístico."""
    if cfg is None or not _is_distillable(task):
        return None
    from okami.llm import providers as prov

    seq = " → ".join(s.tool for s in task.steps
                     if s.tool not in ("task_complete", "task_blocked", "need_input"))
    schema = {"type": "object", "properties": {"name": {"type": "string"}, "body": {"type": "string"}},
              "required": ["name", "body"]}
    msgs = [{"role": "system", "content": "Destila uma SKILL.md REUTILIZÁVEL da tarefa concluída. "
             "'name' = TÓPICO curto em kebab-case, 2 a 4 palavras (≤32 chars), descrevendo a CAPACIDADE "
             "genérica (ex.: 'analise-de-codigo', 'deploy-docker', 'busca-em-logs'). NUNCA copie a frase "
             "do usuário, NUNCA use 'eu/voce/agora/pra/por-favor' nem verbos de pedido. "
             "'body' = markdown com '## Quando usar', '## Como' (passos genéricos), '## Cuidados'. "
             "Conciso e genérico (não específico demais)."},
            {"role": "user", "content": f"OBJETIVO: {task.goal}\nSEQUÊNCIA DE TOOLS: {seq}\n"
             f"RESULTADO: {(task.result or '')[:300]}"}]
    try:
        d = json.loads(prov.complete_messages(cfg, msgs, provider=provider, response_schema=schema))
        # mesmo o nome do LLM passa pelo limpador (tira filler/frase literal se o modelo escorregar);
        # sem 'name' → deriva do objetivo (conteúdo), não da frase crua.
        tools = [s.tool for s in task.steps if s.tool not in ("task_complete", "task_blocked", "need_input")]
        name = _skill_name(str(d.get("name") or task.goal), tools=tools)
        body = str(d.get("body") or "")
        return {"name": name, "body": body} if name and len(body) > 40 else None
    except Exception:  # noqa: BLE001
        return None


def _render_skill_md(sk: dict, task: Task) -> str:
    """Empacota a skill destilada com frontmatter — captura a FRASE REAL do pedido como `intent_example`.
    É isso que faz a skill aprendida ser achável por INTENÇÃO (não só pelo nome) na próxima tarefa
    parecida — o loop que fecha 'skills difíceis de acionar'. Se o distilador já trouxe frontmatter,
    respeita (não duplica)."""
    import yaml

    body = (sk.get("body") or "").strip()
    if body.startswith("---"):
        return body + "\n"
    goal = (task.goal or "").strip()
    meta = {
        "name": sk["name"],
        "description": (sk.get("description") or goal)[:160],
        "intent_examples": [goal[:200]] if goal else [],   # a frase literal do usuário vira âncora de intenção
        "origin": "auto-distilled",                        # marcado → `okami skills prune` poda com precisão
    }
    return "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + body + "\n"


def maybe_write_skill(task: Task, skills_dir: str = "skills", model_name: str = "?", cfg=None) -> str | None:
    """Destila (LLM se `cfg`, senão determinístico) → ESCANEIA (segurança, regra do usuário: skill
    criada pelo agente é validada antes de ativar) → grava em skills/<name>/SKILL.md COM frontmatter
    (intent_examples = pedido real → achável por intenção). Devolve nome/None."""
    from okami.skills.skill_security import Severity, scan_text

    sk = distill_skill_llm(cfg, task) or distill_skill(task, model_name)
    if not sk:
        return None
    if any(f.severity >= Severity.HIGH for f in scan_text(sk["name"], sk["body"])):
        return None                                       # nunca ativa skill insegura (defesa em profundidade)
    f = Path(skills_dir) / sk["name"] / "SKILL.md"
    if f.exists():
        return None                                       # não sobrescreve skill existente
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_render_skill_md(sk, task), encoding="utf-8", newline="\n")
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
    if not m or m["runs"] < 3:
        return {}
    if m["violations"] / max(1, m["runs"]) >= 1.0:
        return {"tool_mode": "json_constrained"}
    return {}
