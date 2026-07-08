"""todo_write — CHECKLIST operacional do modelo que sobrevive à compactação (item 9).

O agente registra os passos do trabalho em `ctx.todos`; quando o histórico é compactado,
`render_pending` reinjeta só os itens em aberto pra ele continuar de onde parou em vez de
recomeçar. A lista é SUBSTITUÍDA inteira a cada chamada (snapshot do plano atual), igual ao
TodoWrite dos harnesses de referência.
"""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult

# Os quatro estados de um item. Qualquer outro valor é coagido pra "pending" (fail-open).
# "cancelled" (paridade Hermes TODO_SCHEMA) — item que não vai mais ser feito, mas fica no
# histórico em vez de sumir (diferente de simplesmente remover da lista).
_STATUS = {"pending", "in_progress", "completed", "cancelled"}


def _coerce(todos: list) -> list[dict]:
    """Normaliza a lista crua → itens {id, content, status} válidos.

    Levanta ValueError na primeira forma inválida (item não-dict ou sem `content`),
    pra a tool devolver ok=False sem mexer em `ctx.todos`.
    """
    out: list[dict] = []
    for i, raw in enumerate(todos):
        if not isinstance(raw, dict):
            raise ValueError(f"todo #{i + 1} não é um objeto (esperado {{id, content, status}}).")
        content = raw.get("content")
        if not content or not str(content).strip():
            raise ValueError(f"todo #{i + 1} sem `content` (todo item precisa de um texto).")
        status = raw.get("status")
        if status not in _STATUS:                      # ausente/inválido → pending (fail-open)
            status = "pending"
        tid = raw.get("id")
        if not tid or not str(tid).strip():            # gera id estável se faltar
            tid = str(i + 1)
        out.append({"id": str(tid), "content": str(content), "status": status})
    return out


def _render_list(todos: list) -> str:
    """Texto da lista atual — devolvido tanto pela leitura (sem `todos`) quanto pela escrita."""
    if not todos:
        return "(checklist vazia)"
    return "\n".join(f"  [{t['status']}] {t['id']}: {t['content']}" for t in todos)


def _merge(existentes: list[dict], incoming: list[dict]) -> list[dict]:
    """merge=true: atualiza por `id` (upsert) em vez de substituir a lista inteira. Item com id já
    existente tem content/status ATUALIZADOS in place (preserva a ordem); id novo é ADICIONADO no
    fim. Sem isto, marcar 1 item como completed exigia reenviar a checklist inteira a cada chamada."""
    by_id = {t["id"]: dict(t) for t in existentes}
    ordem = [t["id"] for t in existentes]
    for t in incoming:
        if t["id"] not in by_id:
            ordem.append(t["id"])
        by_id[t["id"]] = t
    return [by_id[i] for i in ordem]


class TodoWrite(Tool):
    name = "todo_write"
    description = (
        "Mantém sua CHECKLIST operacional do trabalho. Sem `todos` = LÊ a lista atual (não muda nada). "
        "Com `todos` = substitui a lista INTEIRA (default) ou, com `merge=true`, faz UPSERT por `id` "
        "(atualiza os itens citados, mantém o resto) — útil pra marcar 1 item `completed` sem reenviar "
        "tudo. Os itens em aberto sobrevivem à compactação do histórico. Marque cada item `completed` "
        "(ou `cancelled` se não vai mais ser feito) assim que resolver."
    )
    args_schema = {
        "todos": ("(opc) lista de itens [{id, content, status}] onde status ∈ {pending, in_progress, "
                  "completed, cancelled}; omita p/ só LER a lista atual"),
        "merge": "(opc) true = upsert por id (atualiza citados, mantém o resto) em vez de substituir a lista inteira",
    }
    required = ()
    arg_types = {"merge": "boolean"}
    arg_constraints = {"merge": {"default": False}}
    terminal = False

    def run(self, args, ctx) -> ToolResult:
        todos = args.get("todos")
        if todos is None:                               # sem `todos` → leitura pura (não mexe em ctx.todos)
            return ToolResult(True, _render_list(ctx.todos), False)
        if not isinstance(todos, list):
            return ToolResult(False, "todo_write exige `todos` como lista de itens (ou omita p/ ler).", False)
        try:
            normalizado = _coerce(todos)
        except ValueError as e:
            return ToolResult(False, str(e), False)
        if args.get("merge"):
            normalizado = _merge(list(ctx.todos), normalizado)
        ctx.todos[:] = normalizado                     # substitui/atualiza in-place (mesma ref)
        abertos = sum(1 for t in normalizado if t["status"] not in ("completed", "cancelled"))
        return ToolResult(True, f"todo atualizado: {abertos} aberto(s)", False)


def render_pending(todos: list) -> str:
    """Bloco de reinjeção pós-compactação — só os itens pending/in_progress.

    "" quando não há nada em aberto (nada a lembrar). Caso contrário, um cabeçalho que diz ao
    modelo pra CONTINUAR de onde parou + uma linha "  [status] content" por item em aberto.
    Importada por loop/compaction.
    """
    pendentes = [t for t in (todos or [])
                 if isinstance(t, dict) and t.get("status") in ("pending", "in_progress")]
    if not pendentes:
        return ""
    linhas = [
        "[CHECKLIST OPERACIONAL ATIVA — itens pendentes que voce definiu; "
        "continue de onde parou, NAO recomece]"
    ]
    for t in pendentes:
        linhas.append(f"  [{t.get('status')}] {t.get('content')}")
    return "\n".join(linhas)
