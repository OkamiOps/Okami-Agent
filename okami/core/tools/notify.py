"""Tool `notify` (item 3 da pesquisa #7): manda uma mensagem ao DONO AGORA.

Diferente da resposta normal (que sai no fim do turno), `notify` é um aviso FORA
do turno: "terminei", "preciso de aprovação", "alerta". O canal real é o hook
`ctx.notify` (Callable[[str], bool] | None) — em CLI/lib sem dono ele é None, e a
tool falha em paz (fail-open), sem levantar exceção e sem encerrar o turno.
"""

from __future__ import annotations

from okami.core.tools.base import Tool, ToolContext, ToolResult


class Notify(Tool):
    name = "notify"
    description = (
        "Envia uma mensagem ao dono AGORA, fora da resposta normal do turno. "
        "Use para avisar que terminou, que precisa de aprovação, ou disparar um alerta."
    )
    args_schema = {"message": "o texto a entregar ao dono"}
    required = ("message",)
    terminal = False

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        msg = str(args.get("message") or "").strip()
        if not msg:
            return ToolResult(False, "notify exige message", False)

        fn = getattr(ctx, "notify", None)
        if fn is None:
            return ToolResult(
                False,
                "canal de saída indisponível neste contexto (CLI/lib sem dono).",
                False,
            )

        ok = bool(fn(msg))
        return ToolResult(ok, "entregue" if ok else "falha ao entregar", effect=ok)
