"""Kanban swarm v1 — topologia fina de enxame (#12, port do Hermes hermes_cli/kanban_swarm.py).

Sem 2º scheduler: monta um pequeno grafo de trabalho —

    root (planejamento)
      ├─ workers especialistas em PARALELO
      └─ verificador (espera os workers)
           └─ sintetizador (espera o verificador)

O blackboard compartilhado é low-tech: linhas JSON num arquivo (no Hermes, comentários na task-raiz).
Cada worker lê o handoff dos irmãos antes de trabalhar. O Okami EXECUTA via a delegação/spawn que já
existe — aqui mora o PLAN (prompts + protocolo) + o blackboard.
"""
from __future__ import annotations

import json
from pathlib import Path

_PROTOCOL = ("\n\n## Protocolo do swarm\n"
            "- Blackboard compartilhado: `{bb}` (linhas JSON: author/data). LEIA antes de trabalhar e "
            "ESCREVA seu achado ao terminar.\n"
            "- Você é UM especialista; não refaça o trabalho dos irmãos — complemente.\n")


def build_swarm_plan(goal: str, workers: list[dict], *, blackboard: str = ".okami/swarm.json") -> dict:
    """Grafo do swarm a partir do `goal` e da lista de workers ({title, body, [profile], [skills]}).
    Cada worker ganha um prompt com o protocolo de blackboard; verificador e sintetizador idem."""
    g = (goal or "").strip()
    if not g:
        raise ValueError("goal é obrigatório")
    if not workers:
        raise ValueError("ao menos 1 worker")
    proto = _PROTOCOL.format(bb=blackboard)
    wk = []
    for w in workers:
        title = (w.get("title") or "").strip()
        body = (w.get("body") or "").strip()
        wk.append({
            "title": title, "profile": w.get("profile", "default"), "skills": list(w.get("skills") or []),
            "prompt": f"META DO SWARM: {g}\n\nSEU PAPEL ({title}): {body}{proto}",
        })
    verifier = {"prompt": f"META DO SWARM: {g}\n\nVocê é o VERIFICADOR. Leia o blackboard `{blackboard}`, "
                          "cheque a qualidade/consistência dos achados dos workers, aponte lacunas e o que "
                          "precisa refazer. Escreva seu veredito no blackboard."}
    synth = {"prompt": f"META DO SWARM: {g}\n\nVocê é o SINTETIZADOR. Leia o blackboard `{blackboard}` "
                       "(achados + veredito do verificador) e produza a ENTREGA final consolidada p/ o dono."}
    return {"goal": g, "blackboard": blackboard, "workers": wk, "verifier": verifier, "synthesizer": synth}


def blackboard_append(path, author: str, data: dict) -> None:
    """Acrescenta uma entrada {author, data} ao blackboard (JSON-lines). Lock cross-processo: vários
    workers (subagentes) escrevendo em paralelo NÃO intercalam meia-linha (corromperia o JSON)."""
    from okami.core.filelock import _FileLock
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"author": author, "data": data}, ensure_ascii=False) + "\n"
    with _FileLock(p):
        with p.open("a", encoding="utf-8") as f:
            f.write(line)


def blackboard_read(path) -> list[dict]:
    """Lê as entradas do blackboard (lista de {author, data}); [] se não existe/ilegível."""
    p = Path(path)
    if not p.exists():
        return []
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out


def run_swarm(goal: str, workers: list[dict], *, run_fn, blackboard: str = ".okami/swarm.json") -> dict:
    """ORQUESTRA o plano: roda cada worker (via `run_fn(prompt) -> texto`), escreve o achado no
    blackboard, roda o verificador, depois o sintetizador. `run_fn` é injetável (= um wrapper de
    run_task/spawn). Worker que explode é ISOLADO (não derruba o swarm). Devolve {workers, verdict, synthesis}.

    Sequencial por padrão (blackboard compartilhado + isolamento simples); paralelizar é trocar o laço
    por spawn concorrente quando o run_fn for thread-safe."""
    plan = build_swarm_plan(goal, workers, blackboard=blackboard)
    bb = plan["blackboard"]
    def _call(prompt: str, role: str) -> str:
        try:
            out = run_fn(prompt)
        except Exception as e:  # noqa: BLE001 — etapa isolada
            return f"[{role} falhou: {e}]"
        return out if isinstance(out, str) else ("" if out is None else str(out))  # contrato: sempre str

    results = []
    for w in plan["workers"]:
        out = _call(w["prompt"], f"worker {w['title']}")
        results.append({"title": w["title"], "output": out})
        blackboard_append(bb, f"worker:{w['title']}", {"output": out})
    verdict = _call(plan["verifier"]["prompt"], "verificador")
    blackboard_append(bb, "verifier", {"verdict": verdict})
    synthesis = _call(plan["synthesizer"]["prompt"], "sintetizador")
    blackboard_append(bb, "synthesizer", {"synthesis": synthesis})
    return {"workers": results, "verdict": verdict, "synthesis": synthesis}


__all__ = ["build_swarm_plan", "blackboard_append", "blackboard_read", "run_swarm"]
