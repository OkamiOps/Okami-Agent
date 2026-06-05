"""Adapter Paperclip (§11/§13) — Okami "contratado" numa empresa de IA (paperclip.ing).

Paperclip é um CONTROL PLANE (não um framework de agente): ele ACORDA o agente num *heartbeat*,
injeta env vars (identidade, run-id, api-key) e dá a *issue* (tarefa) atribuída. O agente faz
**checkout**, trabalha UMA vez no heartbeat (nosso harness), e reporta o status (done/blocked/
in_review) com um comentário durável. Confirmações viram *interactions*; trabalho longo/paralelo
vira *issue filha* (Paperclip acorda o pai quando terminam — nada de polling).

Contrato (docs.paperclip.ing/guides/agent-developer/heartbeat-protocol):
- Auth: `Authorization: Bearer $PAPERCLIP_API_KEY` + `X-Paperclip-Run-Id: $PAPERCLIP_RUN_ID`.
- Env injetadas: PAPERCLIP_API_URL, PAPERCLIP_API_KEY, PAPERCLIP_AGENT_ID, PAPERCLIP_COMPANY_ID,
  PAPERCLIP_RUN_ID; opcionais PAPERCLIP_TASK_ID, PAPERCLIP_APPROVAL_ID, PAPERCLIP_WAKE_REASON,
  PAPERCLIP_WAKE_COMMENT_ID.
Regras DURAS: sempre checkout antes de trabalhar; NUNCA repetir um 409; sempre comentar antes de
sair; usar issue filha em vez de polling; nunca pedir p/ humano fazer trabalho de agente (escala).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

# Status que o agente pode assumir numa issue (ordem de prioridade de trabalho no heartbeat).
_WORK_STATUSES = ["in_progress", "in_review", "todo", "blocked"]
_CHECKOUT_EXPECTED = ["todo", "backlog", "blocked", "in_review"]


class PaperclipError(RuntimeError):
    pass


class PaperclipConflict(PaperclipError):
    """409 no checkout — a issue é de outro agente. NUNCA repetir."""


class PaperclipClient:
    """Cliente HTTP do Paperclip (urllib, sem dep extra). Headers de auth + run-id automáticos."""

    def __init__(self, api_url: str, api_key: str, run_id: str | None = None, timeout: float = 60.0):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.run_id = run_id
        self.timeout = timeout

    @classmethod
    def from_env(cls, env=None) -> "PaperclipClient":
        env = env or os.environ
        url = env.get("PAPERCLIP_API_URL")
        key = env.get("PAPERCLIP_API_KEY")
        if not url or not key:
            raise PaperclipError("faltam PAPERCLIP_API_URL / PAPERCLIP_API_KEY (injetadas pelo Paperclip).")
        return cls(url, key, run_id=env.get("PAPERCLIP_RUN_ID"))

    def _url(self, path: str) -> str:
        # PAPERCLIP_API_URL pode já terminar em /api; os paths começam com /api/...
        if path.startswith("/api/") and self.api_url.endswith("/api"):
            path = path[4:]
        return f"{self.api_url}{path}"

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self._url(path), data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.run_id and method in ("POST", "PATCH", "PUT", "DELETE"):
            req.add_header("X-Paperclip-Run-Id", self.run_id)   # obrigatório em modificações
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
                raw = r.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:                      # noqa: PERF203
            if e.code == 409:
                raise PaperclipConflict(f"409 em {method} {path}") from e
            detail = e.read().decode("utf-8", "replace")[:300]
            raise PaperclipError(f"{e.code} em {method} {path}: {detail}") from e

    # ---- Endpoints do protocolo de heartbeat ----------------------------------------------
    def me(self) -> dict:
        return self._call("GET", "/api/agents/me")

    def list_issues(self, company_id: str, agent_id: str, statuses=None) -> list[dict]:
        st = ",".join(statuses or _WORK_STATUSES)
        res = self._call("GET", f"/api/companies/{company_id}/issues?assigneeAgentId={agent_id}&status={st}")
        return res.get("issues", res) if isinstance(res, dict) else res

    def get_issue(self, issue_id: str) -> dict:
        return self._call("GET", f"/api/issues/{issue_id}")

    def heartbeat_context(self, issue_id: str) -> dict:
        """Contexto compacto (preferido ao thread inteiro). Cai p/ get_issue se não existir."""
        try:
            return self._call("GET", f"/api/issues/{issue_id}/heartbeat-context")
        except PaperclipError:
            return self.get_issue(issue_id)

    def checkout(self, issue_id: str, agent_id: str, expected_statuses=None) -> dict:
        """Toma posse da issue. Levanta PaperclipConflict em 409 (NUNCA repetir)."""
        return self._call("POST", f"/api/issues/{issue_id}/checkout",
                          {"agentId": agent_id, "expectedStatuses": expected_statuses or _CHECKOUT_EXPECTED})

    def comment(self, issue_id: str, text: str) -> dict:
        return self._call("POST", f"/api/issues/{issue_id}/comments", {"body": text})

    def patch_issue(self, issue_id: str, status: str, comment: str) -> dict:
        return self._call("PATCH", f"/api/issues/{issue_id}", {"status": status, "comment": comment})

    def create_interaction(self, issue_id: str, kind: str, prompt: str, payload: dict | None = None) -> dict:
        body = {"type": kind, "prompt": prompt}
        if payload:
            body.update(payload)
        return self._call("POST", f"/api/issues/{issue_id}/interactions", body)

    def create_child_issue(self, company_id: str, title: str, assignee_agent_id: str,
                           parent_id: str, goal_id: str | None = None) -> dict:
        body = {"title": title, "assigneeAgentId": assignee_agent_id, "parentId": parent_id}
        if goal_id:
            body["goalId"] = goal_id
        return self._call("POST", f"/api/companies/{company_id}/issues", body)


# --------------------------------------------------------------------------- orquestração
@dataclass
class HeartbeatResult:
    ok: bool
    issue_id: str | None = None
    status: str | None = None          # done | blocked | in_review | none
    detail: str = ""


def _pick_issue(issues: list[dict], task_id: str | None) -> dict | None:
    """Prioridade: PAPERCLIP_TASK_ID → in_progress → in_review → todo. Pula 'blocked'."""
    if not issues:
        return None
    if task_id:
        for it in issues:
            if str(it.get("id")) == str(task_id):
                return it
    order = {"in_progress": 0, "in_review": 1, "todo": 2}
    actionable = [it for it in issues if it.get("status") in order]
    actionable.sort(key=lambda it: (order.get(it.get("status"), 9), -(it.get("priority", 0) or 0)))
    return actionable[0] if actionable else None


def _issue_goal(issue: dict, ctx: dict) -> str:
    title = issue.get("title", "(sem título)")
    body = issue.get("body") or issue.get("description") or ctx.get("summary") or ""
    return f"{title}\n\n{body}".strip()


def _ctx_block(issue: dict, ctx: dict) -> str:
    bits = [f"ISSUE #{issue.get('id')} · status={issue.get('status')} · prioridade={issue.get('priority')}"]
    comments = ctx.get("comments") or issue.get("comments") or []
    for c in comments[-6:]:
        who = c.get("authorName") or c.get("agentId") or c.get("author") or "?"
        bits.append(f"  comentário {who}: {(c.get('body') or '')[:300]}")
    return "CONTEXTO PAPERCLIP (continue o trabalho, não repita):\n" + "\n".join(bits)


def _auto_approve(mode: str) -> bool:
    """Quem auto-aprova ação sensível SEM humano: SÓ 'yolo'. 'off'/'defer'/resto = NÃO (fail-closed)."""
    return mode == "yolo"


# Marcadores de EVIDÊNCIA MATERIAL num relatório de conclusão (#P1 — board bonito e falso é veneno).
# Paperclip é control plane: 'complete' do agente NÃO basta p/ marcar done — precisa de prova verificável
# (arquivo tocado, comando/teste rodado, commit, fonte, URL, ou uma seção de handoff explícita).
_EVIDENCE_PATTERNS = (
    r"```",                                              # bloco de código (diff/saída/comando)
    r"\b[\w./-]+\.(py|ts|tsx|js|jsx|md|yaml|yml|json|toml|rs|go|sql|sh|css|html)\b",  # caminho de arquivo
    r"\b[0-9a-f]{7,40}\b",                               # hash de commit
    r"https?://",                                        # fonte/URL
    r"\$\s|\bpytest\b|\bnpm\b|\bcargo\b|\bgit\b|\buv run\b",   # comando rodado
    r"\b\d+\s+(test|teste|passed|passaram|ok)\b",        # resultado de teste
    r"\b(evid[êe]ncia|artefato|arquivo|commit|teste|resultado|sa[íi]da|pull request)\s*[:=]",  # handoff
)
_EVIDENCE_RE = re.compile("|".join(_EVIDENCE_PATTERNS), re.IGNORECASE)


def has_material_evidence(result: str, *, min_len: int = 40) -> bool:
    """True se o relatório tem prova material (não só "Concluído"/"Feito"). Heurística conservadora:
    exige um marcador de evidência E corpo mínimo — senão o trabalho vira in_review, não done."""
    text = (result or "").strip()
    if len(text) < min_len:
        return False                                     # "Concluído." / "Feito" → sem prova
    return bool(_EVIDENCE_RE.search(text))


_HANDOFF_HINT = ("Para fechar como **done**, o relatório precisa de EVIDÊNCIA material: arquivo(s) "
                 "tocado(s), comando/teste rodado (ex.: `pytest`), commit/PR, ou fonte. Sem isso, "
                 "fica em revisão (board bonito sem prova não conta).")


def run_heartbeat(cfg, workspace, *, run_task, client: PaperclipClient | None = None, env=None,
                  approve_mode: str = "defer", emit=lambda m: None) -> HeartbeatResult:
    """UMA batida de heartbeat: identifica → pega a issue → checkout → harness → reporta status.

    `approve_mode`: 'defer' (ações sensíveis criam interaction request_confirmation e a tarefa fica
    in_review p/ humano — governança), 'yolo' (auto-aprova tudo). 'off' = NÃO auto-aprova (fail-closed,
    igual ao core/gateway): adia como o defer. SÓ yolo libera ação sensível sem humano (P0.3).
    """
    from okami.core import TaskState

    env = env or os.environ
    client = client or PaperclipClient.from_env(env)

    me = client.me()
    agent_id = me.get("id") or env.get("PAPERCLIP_AGENT_ID")
    company_id = (me.get("companyId") or (me.get("company") or {}).get("id")
                  or env.get("PAPERCLIP_COMPANY_ID"))
    from okami.core.tool_policy import paperclip_surface
    surface = paperclip_surface(me.get("role"))      # #P1: papel → repertório de tools (worker/manager/…)
    emit(f"sou {agent_id} @ {company_id} · papel={me.get('role')} (surface={surface}) · budget={me.get('budget')}")

    issues = client.list_issues(company_id, agent_id)
    issue = _pick_issue(issues, env.get("PAPERCLIP_TASK_ID"))
    if not issue:
        emit("nenhuma issue acionável neste heartbeat.")
        return HeartbeatResult(ok=True, status="none", detail="sem trabalho")

    issue_id = str(issue["id"])
    try:
        client.checkout(issue_id, agent_id)
    except PaperclipConflict:
        emit(f"issue {issue_id}: 409 (de outro agente) — parando, sem retry.")
        return HeartbeatResult(ok=True, issue_id=issue_id, status="none", detail="409 conflict")

    ctx = client.heartbeat_context(issue_id)
    goal = _issue_goal(issue, ctx)
    emit(f"trabalhando na issue {issue_id}: {issue.get('title')}")

    pending: list[str] = []                                  # ações sensíveis adiadas (governança)

    def approve(req: dict) -> bool:
        if _auto_approve(approve_mode):        # SÓ yolo auto-aprova — off NÃO (fail-closed, P0.3)
            return True
        # defer: cria uma interação de confirmação e ADIA (não faz a ação sensível agora)
        try:
            client.create_interaction(issue_id, "request_confirmation",
                                       f"Aprovar ação sensível: {req.get('reason')}?",
                                       {"category": req.get("category"), "risk": req.get("risk")})
        except PaperclipError:
            pass
        pending.append(req.get("reason", "ação sensível"))
        return False

    task = run_task(cfg, workspace, goal, approve=approve, extra_context=_ctx_block(issue, ctx),
                    surface=surface, emit=emit)               # #P1: surface por papel (não mais 'paperclip' fixo)

    if pending and task.state != TaskState.COMPLETE:
        comment = ("Aguardando confirmação humana p/ ações sensíveis:\n- "
                   + "\n- ".join(pending) + f"\n\nProgresso: {task.result or task.reason or ''}")
        client.patch_issue(issue_id, "in_review", comment)
        return HeartbeatResult(ok=True, issue_id=issue_id, status="in_review", detail="confirmação pendente")
    if task.state == TaskState.COMPLETE:
        # #P1: control plane NÃO marca done só porque o agente disse 'complete' — exige evidência material.
        # Sem prova verificável (arquivo/comando/teste/commit/fonte) → in_review, não done (board falso é veneno).
        require_evidence = bool((getattr(cfg, "paperclip", None) or {}).get("require_evidence", True))
        if require_evidence and not has_material_evidence(task.result or ""):
            comment = (f"Marcado como concluído pelo agente, mas SEM evidência material.\n\n"
                       f"Resultado: {(task.result or '(vazio)')[:800]}\n\n{_HANDOFF_HINT}")
            client.patch_issue(issue_id, "in_review", comment)
            emit("⚠ complete SEM evidência material → in_review (não done).")
            return HeartbeatResult(ok=True, issue_id=issue_id, status="in_review",
                                   detail="sem evidência material")
        client.patch_issue(issue_id, "done", task.result or "Concluído.")
        return HeartbeatResult(ok=True, issue_id=issue_id, status="done", detail=task.result or "")
    if task.state == TaskState.NEEDS_INPUT:
        client.create_interaction(issue_id, "request_confirmation", task.reason or "Preciso de uma decisão.")
        client.patch_issue(issue_id, "in_review", task.reason or "Aguardando input.")
        return HeartbeatResult(ok=True, issue_id=issue_id, status="in_review", detail=task.reason or "")
    # BLOCKED / FAILED
    client.patch_issue(issue_id, "blocked", task.reason or "Bloqueado — não foi possível concluir.")
    return HeartbeatResult(ok=True, issue_id=issue_id, status="blocked", detail=task.reason or "")
