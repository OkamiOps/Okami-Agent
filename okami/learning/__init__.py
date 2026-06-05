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
    """Extrai lições do resultado da tarefa (sem rede)."""
    stats = task.stats or {}
    n = len(task.steps)
    out: list[MemoryItem] = []

    if task.state in (TaskState.FAILED, TaskState.BLOCKED):
        out.append(MemoryItem(
            kind="anti_pattern", source="reflection",
            text=(f"ANTI-PADRÃO ({model_name}): '{task.goal[:120]}' terminou {task.state.value} "
                  f"— {task.reason}. (passos={n}, violations={stats.get('violations', 0)}, "
                  f"loops={stats.get('loops', 0)}, rejeições={stats.get('gate_rejections', 0)}). "
                  "Da próxima vez: decomponha mais, verifique antes de seguir, evite repetir a ação."),
        ))
    elif task.state == TaskState.COMPLETE and n >= 3:
        seq = " → ".join(s.tool for s in task.steps)
        out.append(MemoryItem(
            kind="lesson", source="reflection",
            text=f"COMO: para '{task.goal[:120]}' funcionou a sequência: {seq}.",
        ))
    return out


def apply(memory, task: Task, model_name: str = "?") -> list[MemoryItem]:
    """Reflete e GRAVA as lições na memória (defensivo: nunca derruba o fluxo)."""
    lessons = reflect(task, model_name)
    if memory is not None:
        for lesson in lessons:
            try:
                memory.write(lesson)
            except Exception:  # noqa: BLE001
                pass
    return lessons


# ----------------------------------------------------- AUTO-SKILL (Fase 5, estilo Hermes "skill from experience")
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def distill_skill(task: Task, model_name: str = "?") -> dict | None:
    """Destila uma SKILL.md de uma tarefa BEM-sucedida e NÃO-trivial (≥4 passos, ≥2 tools distintas).
    Devolve {name, body} ou None. Determinístico (a versão por LLM entra depois)."""
    if task.state != TaskState.COMPLETE:
        return None
    tools = [s.tool for s in task.steps if s.tool not in ("task_complete", "task_blocked", "need_input")]
    if len(tools) < 4 or len(set(tools)) < 2:
        return None
    name = _slug(task.goal)
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
    if cfg is None or task.state != TaskState.COMPLETE:
        return None
    from okami.llm import providers as prov

    seq = " → ".join(s.tool for s in task.steps
                     if s.tool not in ("task_complete", "task_blocked", "need_input"))
    schema = {"type": "object", "properties": {"name": {"type": "string"}, "body": {"type": "string"}},
              "required": ["name", "body"]}
    msgs = [{"role": "system", "content": "Destila uma SKILL.md REUTILIZÁVEL da tarefa concluída. "
             "'name'=slug curto kebab; 'body'=markdown com '## Quando usar', '## Como' (passos "
             "genéricos), '## Cuidados'. Conciso e genérico (não específico demais)."},
            {"role": "user", "content": f"OBJETIVO: {task.goal}\nSEQUÊNCIA DE TOOLS: {seq}\n"
             f"RESULTADO: {(task.result or '')[:300]}"}]
    try:
        d = json.loads(prov.complete_messages(cfg, msgs, provider=provider, response_schema=schema))
        name, body = _slug(str(d.get("name") or task.goal)), str(d.get("body") or "")
        return {"name": name, "body": body} if name and len(body) > 40 else None
    except Exception:  # noqa: BLE001
        return None


def maybe_write_skill(task: Task, skills_dir: str = "skills", model_name: str = "?", cfg=None) -> str | None:
    """Destila (LLM se `cfg`, senão determinístico) → ESCANEIA (segurança, regra do usuário: skill
    criada pelo agente é validada antes de ativar) → grava em skills/<name>/SKILL.md. Devolve nome/None."""
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
    f.write_text(sk["body"], encoding="utf-8", newline="\n")
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
