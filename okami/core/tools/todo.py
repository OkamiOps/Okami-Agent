"""todo_write — CHECKLIST operacional do modelo que sobrevive à compactação (item 9).

O agente registra os passos do trabalho em `ctx.todos`; quando o histórico é compactado,
`render_pending` reinjeta só os itens em aberto pra ele continuar de onde parou em vez de
recomeçar. A lista é SUBSTITUÍDA inteira a cada chamada (snapshot do plano atual), igual ao
TodoWrite dos harnesses de referência.
"""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult

# Os três estados de um item. Qualquer outro valor é coagido pra "pending" (fail-open).
_STATUS = {"pending", "in_progress", "completed"}


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


class TodoWrite(Tool):
    name = "todo_write"
    description = (
        "Mantém sua CHECKLIST operacional do trabalho — substitui a lista INTEIRA. Use pra planejar "
        "passos e marcar progresso; os itens em aberto sobrevivem à compactação do histórico, então "
        "você não recomeça do zero. Marque cada item `completed` assim que terminar."
    )
    args_schema = {
        "todos": ("lista de itens [{id, content, status}] onde status ∈ {pending, in_progress, "
                  "completed}; substitui a lista inteira (passe o estado completo a cada vez)"),
    }
    required = ("todos",)
    terminal = False

    def run(self, args, ctx) -> ToolResult:
        todos = args.get("todos")
        if not isinstance(todos, list):
            return ToolResult(False, "todo_write exige `todos` como lista de itens.", False)
        try:
            normalizado = _coerce(todos)
        except ValueError as e:
            return ToolResult(False, str(e), False)
        ctx.todos[:] = normalizado                     # substitui a lista inteira (in-place: mesma ref)
        abertos = sum(1 for t in normalizado if t["status"] != "completed")
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
