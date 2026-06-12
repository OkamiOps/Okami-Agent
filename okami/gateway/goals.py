"""/goal + /subgoal — objetivo PERSISTENTE por chat (pesquisa #5 item 41, paridade Hermes).

O objetivo sobrevive entre turnos (.okami/goals/<chat>.json) e entra no CONTEXTO de cada turno com
moldura de referência (não-sequestro). Um juiz AUXILIAR (modelo barato, fail-open) avalia após cada
turno se algum subgoal foi concluído — e só fecha com EVIDÊNCIA CONCRETA (gate determinístico: "feito"
não fecha nada). Orçamento de turnos evita objetivo-zumbi consumindo contexto pra sempre.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

_GENERIC = {"feito", "done", "ok", "concluído", "concluido", "pronto", "sim", "yes", "completo"}


def concrete_evidence(evidence: str, subgoal_text: str) -> bool:
    """Gate DETERMINÍSTICO de evidência (o juiz exige prova, não opinião): precisa ter substância
    (≥15 chars), não ser genérica ('feito'/'ok') e não ser só o texto do subgoal repetido."""
    ev = (evidence or "").strip()
    if len(ev) < 15:
        return False
    if ev.lower().rstrip(".!") in _GENERIC:
        return False
    return ev.lower() != (subgoal_text or "").strip().lower()


class GoalStore:
    """Objetivo persistente por chat — JSON em <base>/.okami/goals/<chat>.json (atômico)."""

    def __init__(self, base):
        self._dir = Path(base) / ".okami" / "goals"

    def _path(self, chat_id) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(chat_id)) or "default"
        return self._dir / f"{safe}.json"

    def get(self, chat_id) -> dict | None:
        try:
            return json.loads(self._path(chat_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write(self, chat_id, data: dict) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path(chat_id).with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path(chat_id))

    def set_goal(self, chat_id, text: str, *, turn_budget: int = 30) -> dict:
        data = {"goal": str(text).strip(), "created_at": time.time(), "turn_budget": int(turn_budget),
                "turns_used": 0, "done": False, "subgoals": []}
        self._write(chat_id, data)
        return data

    def add_subgoal(self, chat_id, text: str) -> dict | None:
        g = self.get(chat_id)
        if not g:
            return None
        g["subgoals"].append({"text": str(text).strip(), "done": False, "evidence": ""})
        self._write(chat_id, g)
        return g

    def complete_subgoal(self, chat_id, index: int, evidence: str) -> bool:
        g = self.get(chat_id)
        if not g or not (0 <= index < len(g["subgoals"])):
            return False
        g["subgoals"][index]["done"] = True
        g["subgoals"][index]["evidence"] = str(evidence)[:300]
        self._write(chat_id, g)
        return True

    def mark_done(self, chat_id) -> None:
        g = self.get(chat_id)
        if g:
            g["done"] = True
            self._write(chat_id, g)

    def bump_turn(self, chat_id) -> dict | None:
        g = self.get(chat_id)
        if not g or g.get("done"):
            return g
        g["turns_used"] = int(g.get("turns_used", 0)) + 1
        self._write(chat_id, g)
        return g

    def clear(self, chat_id) -> None:
        self._path(chat_id).unlink(missing_ok=True)

    def context_block(self, chat_id) -> str:
        """Bloco p/ o contexto do turno. Moldura de REFERÊNCIA (a fala atual do usuário VENCE —
        anti-sequestro, mesma doutrina da compactação). '' se não há objetivo ativo, se já concluiu,
        ou se o ORÇAMENTO de turnos estourou (objetivo-zumbi não consome contexto pra sempre)."""
        g = self.get(chat_id)
        if not g or g.get("done") or g["turns_used"] >= g["turn_budget"]:
            return ""
        subs = "\n".join(
            f"  {'✅' if s['done'] else '◻'} {i}. {s['text']}" for i, s in enumerate(g["subgoals"]))
        return (f"[OBJETIVO PERSISTENTE deste chat — referência de fundo; a mensagem atual do usuário "
                f"VENCE sempre]\nObjetivo: {g['goal']} (turno {g['turns_used'] + 1}/{g['turn_budget']})"
                + (f"\nSubgoals:\n{subs}" if subs else "")
                + "\nQuando a mensagem atual permitir, avance o objetivo. NÃO declare subgoal "
                  "concluído sem evidência concreta.")

    def status_text(self, chat_id) -> str:
        g = self.get(chat_id)
        if not g:
            return "(sem objetivo ativo — defina com /goal <texto>)"
        flag = "✅ concluído" if g.get("done") else (
            "⏸ orçamento esgotado" if g["turns_used"] >= g["turn_budget"] else "▶ ativo")
        subs = "\n".join(
            f"  {'✅' if s['done'] else '◻'} {i}. {s['text']}"
            + (f" — {s['evidence'][:80]}" if s["done"] and s["evidence"] else "")
            for i, s in enumerate(g["subgoals"])) or "  (sem subgoals — adicione com /subgoal <texto>)"
        return (f"🎯 {g['goal']} [{flag} · turno {g['turns_used']}/{g['turn_budget']}]\n{subs}")


_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "completed": {"type": "array", "items": {
            "type": "object",
            "properties": {"index": {"type": "integer"}, "evidence": {"type": "string"}},
            "required": ["index", "evidence"]}},
        "goal_done": {"type": "boolean"},
    },
    "required": ["completed"],
}

_JUDGE_PROMPT = (
    "Você é um JUIZ de progresso. Dado o objetivo, os subgoals ABERTOS e o resultado do último turno, "
    "diga quais subgoals foram CONCLUÍDOS NESTE TURNO. Regra dura: só marque concluído se o resultado "
    "contém EVIDÊNCIA CONCRETA (saída de comando, arquivo criado, número, citação) — intenção/promessa "
    "NÃO conta. Na dúvida, NÃO marque. Responda só o JSON.")


def judge_turn(cfg, store: GoalStore, chat_id, turn_result: str) -> dict:
    """Juiz auxiliar FAIL-OPEN: avalia o resultado do turno contra os subgoals abertos e fecha os que
    têm evidência concreta (gate determinístico por cima do juiz). LLM indisponível/lixo → no-op.
    Retorna {"completed": [índices fechados], "goal_done": bool}."""
    out = {"completed": [], "goal_done": False}
    g = store.get(chat_id)
    if not g or g.get("done"):
        return out
    open_subs = [(i, s) for i, s in enumerate(g["subgoals"]) if not s["done"]]
    if not open_subs:
        return out
    listing = "\n".join(f"{i}: {s['text']}" for i, s in open_subs)
    msgs = [{"role": "system", "content": _JUDGE_PROMPT},
            {"role": "user", "content": f"OBJETIVO: {g['goal']}\nSUBGOALS ABERTOS:\n{listing}\n\n"
                                        f"RESULTADO DO TURNO:\n{(turn_result or '')[:4000]}"}]
    from okami.llm.aux import aux_complete
    try:
        raw = aux_complete(cfg, "judge", msgs, response_schema=_JUDGE_SCHEMA, max_tokens=300)
    except Exception:  # noqa: BLE001 — juiz é fundo: indisponível → segue sem julgar (fail-open)
        return out
    try:
        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
    except (ValueError, AttributeError):
        return out
    valid = {i for i, _ in open_subs}
    for item in (data.get("completed") or []):
        try:
            idx, ev = int(item.get("index")), str(item.get("evidence", ""))
        except (TypeError, ValueError, AttributeError):
            continue
        if idx in valid and concrete_evidence(ev, g["subgoals"][idx]["text"]):
            store.complete_subgoal(chat_id, idx, ev)
            out["completed"].append(idx)
    if data.get("goal_done") and out["completed"]:
        fresh = store.get(chat_id)
        if fresh and all(s["done"] for s in fresh["subgoals"]):
            store.mark_done(chat_id)
            out["goal_done"] = True
    return out
