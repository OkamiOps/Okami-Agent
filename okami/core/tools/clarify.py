"""Tool `clarify` (#8 item 1) — o agente PERGUNTA ao dono antes de agir em ambiguidade.

Diferente da APROVAÇÃO (que confirma uma ação perigosa já decidida), `clarify` é PRÓ-ativo: o modelo
para ANTES de gastar turnos quando a tarefa tem um trade-off real ou está ambígua ("qual desses 2
repos?", "sobrescrevo ou faço backup?"). O canal real é o hook `ctx.clarify(question, options) -> str`
(bloqueante, com timeout no gateway). Sem dono interativo (cron/autônomo/lib) o hook é None e a tool
falha em paz, mandando o modelo seguir com um default razoável (nunca trava).
"""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolContext, ToolResult

_FOLLOW_DEFAULT = "siga com um default razoável e diga qual suposição você fez."


def parse_options(raw) -> list[str]:
    """Opções de um menu: lista → como veio; string 'a|b|c' → split por '|'; vazio/None → []."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(o).strip() for o in raw if str(o).strip()]
    return [o.strip() for o in str(raw).split("|") if o.strip()]


class Clarify(Tool):
    name = "clarify"
    description = ("PERGUNTE ao dono antes de agir quando a tarefa está AMBÍGUA ou tem um trade-off real "
                   "que muda o resultado (qual de 2 abordagens, qual repo/arquivo). NÃO use p/ confirmar "
                   "comando perigoso (a aprovação já cuida); se for baixo risco, escolha um default em vez "
                   "de perguntar. Bloqueia até a resposta.")
    args_schema = {"question": "a pergunta (clara, 1 frase)",
                   "options": "(opc) opções separadas por '|' → vira menu; sem isso = resposta aberta"}
    required = ("question",)
    terminal = False

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        q = str(args.get("question") or "").strip()
        if not q:
            return ToolResult(False, "clarify exige 'question' não-vazio.", False)
        fn = getattr(ctx, "clarify", None)
        if fn is None:
            return ToolResult(False, f"não há dono interativo p/ perguntar agora — {_FOLLOW_DEFAULT}", False)
        options = parse_options(args.get("options"))
        try:
            answer = fn(q, options)
        except Exception as e:  # noqa: BLE001 — falha do canal nunca derruba o turno
            return ToolResult(False, f"falha ao perguntar ({e}) — {_FOLLOW_DEFAULT}", False)
        if answer is None or not str(answer).strip():
            return ToolResult(False, f"sem resposta do dono (timeout) — {_FOLLOW_DEFAULT}", False)
        return ToolResult(True, f"o dono respondeu: {str(answer).strip()}", effect=False)
