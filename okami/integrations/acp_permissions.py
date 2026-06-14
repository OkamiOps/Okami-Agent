"""ACP §13 — edit-approval + permissions (pesquisa #7 item 13, fecha o D28 sobre-declarado).

Helpers PUROS (sem I/O, sem estado) que traduzem o pedido de aprovação do harness
({tool,args,args_hash,reason,category,risk}) num REQUEST JSON-RPC ACP `session/request_permission`
que o cliente (Zed/VS Code) sabe renderizar:

- `permission_request(req)` → o request inteiro (com `options` allow/reject e o `toolCall`).
  Para write/edit, enriquece com o diff old→new (via `edit_diff`) p/ a IDE mostrar a mudança ANTES
  de escrever. Para run_shell perigoso, anota os riscos humanos (`command_risks`).
- `edit_diff(tool, args, ws)` → {path, old, new}: lê o arquivo atual e computa o texto pós-edição,
  sem TOCAR no disco (é só pra prévia). Fail-open: erro de leitura → old vazio.

O round-trip BLOQUEANTE (mandar o request, esperar a resposta do cliente) vive em acp.py — aqui é só
a forma do envelope, testável sem stdio.
"""

from __future__ import annotations

import os
from pathlib import Path

# tools que ESCREVEM em arquivo (mesma trava do classify) → merecem prévia de diff.
_WRITE_TOOLS = ("write_file", "edit_file")


def edit_diff(tool: str, args: dict, ws) -> dict:
    """{path, old, new} p/ a prévia de diff de uma escrita. NÃO escreve nada (só lê o atual e simula).

    - write_file: new = `content` inteiro; old = conteúdo atual (vazio se não existe).
    - edit_file: aplica a substituição old→new in-memory sobre o conteúdo atual.
    Fail-open: qualquer erro de leitura → old="" (a IDE ainda vê o new como adição)."""
    args = args or {}
    rel = str(args.get("path", "") or "")
    old = ""
    try:
        # JAIL: a prévia NUNCA lê fora do workspace. Path absoluto ou '..' que escapa a base → sem old
        # (senão um edit_file com path=/etc/shadow vazaria o arquivo no oldText da prévia de permissão).
        if ws:
            base = Path(ws).resolve()
            p = (base / rel).resolve()
            inside = p == base or str(p).startswith(str(base) + os.sep)
        else:
            p, inside = Path(rel), False
        if inside and p.exists() and p.is_file():
            old = p.read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — prévia é best-effort; sem old ainda dá pra ver a adição
        old = ""

    if tool == "edit_file":
        find = str(args.get("old", "") or "")
        repl = str(args.get("new", "") or "")
        replace_all = bool(args.get("replace_all", False))
        if find and find in old:
            new = old.replace(find, repl) if replace_all else old.replace(find, repl, 1)
        else:                                  # 'old' não casou no atual → mostra ao menos o trecho-alvo
            new = repl or old
    else:                                      # write_file (e qualquer outra escrita de conteúdo inteiro)
        content = args.get("content", "")
        new = content if isinstance(content, str) else ("" if content is None else str(content))

    return {"path": rel, "old": old, "new": new}


def _options() -> list[dict]:
    """As 4 opções de aprovação que o ACP entende, mapeadas p/ o vocabulário do go/no-go do Okami.

    O ACP usa `kind` (allow_once/allow_always/reject_once/reject_always) + `optionId` (o que o cliente
    devolve). Mantemos o optionId no MESMO vocabulário do Approver.prompt do Okami
    (once/session/always/deny) p/ o callback traduzir direto."""
    return [
        {"optionId": "once", "name": "Permitir uma vez", "kind": "allow_once"},
        {"optionId": "session", "name": "Permitir nesta sessão", "kind": "allow_once"},
        {"optionId": "always", "name": "Sempre permitir", "kind": "allow_always"},
        {"optionId": "deny", "name": "Recusar", "kind": "reject_once"},
    ]


def permission_request(req: dict) -> dict:
    """Traduz o req do harness no REQUEST `session/request_permission` do ACP (sem o `id`/`jsonrpc` —
    o emissor em acp.py põe o envelope JSON-RPC e o `_rid`).

    Forma de retorno: {"method": "session/request_permission", "params": {...}}. Para write/edit,
    `toolCall.kind='edit'` + `locations` com o diff old→new; para run_shell perigoso, `toolCall.content`
    com os riscos humanos do command_risks. O `_workspace` opcional no req permite ler o old do disco."""
    req = req or {}
    tool = req.get("tool", "?")
    args = req.get("args") or {}
    category = req.get("category", "")
    risk = req.get("risk", "high")
    reason = req.get("reason", "")

    tool_call: dict = {
        "toolCallId": req.get("args_hash", ""),
        "title": tool,
        "kind": "execute",
        "status": "pending",
    }

    if tool in _WRITE_TOOLS:
        ws = req.get("_workspace")
        diff = edit_diff(tool, args, ws)
        tool_call["kind"] = "edit"
        # `locations` com a prévia old→new — é o que o Zed lê p/ desenhar o diff ANTES de escrever.
        tool_call["locations"] = [{
            "path": diff["path"],
            "oldText": diff["old"],
            "newText": diff["new"],
        }]
    elif tool in ("run_shell", "process_start"):
        cmd = str(args.get("cmd", "") or "")
        from okami.core.approval import command_risks
        risks = command_risks(cmd)
        tool_call["kind"] = "execute"
        tool_call["content"] = [{"type": "content", "content": {"type": "text", "text": cmd}}]
        if risks:                              # riscos humanos anotados (pipe-to-shell, rm -rf, sudo…)
            tool_call["risks"] = risks

    params = {
        "toolCall": tool_call,
        "reason": reason,
        "category": category,
        "risk": risk,
        "options": _options(),
    }
    return {"method": "session/request_permission", "params": params}


def decision_to_bool(decision: str) -> bool:
    """Resposta do cliente (optionId OU kind do ACP) → go/no-go bool. Fail-closed: desconhecido = nega."""
    d = (decision or "").strip().lower()
    return d in ("once", "session", "always", "allow_once", "allow_always", "allow", "allowed")
