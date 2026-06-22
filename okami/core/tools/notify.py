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


class SendMessage(Tool):
    name = "send_message"
    description = (
        "Envia uma mensagem de texto por um canal SEM rodar o LLM (entrega direta — avisos/relatórios). "
        "channel=telegram (padrão). target=chat_id de destino; VAZIO = entrega ao DONO do canal atual. "
        "Usa o token do PRÓPRIO agente (channels.<canal> da config), nunca um token avulso. "
        "Ação sensível (go/no-go)."
    )
    args_schema = {"text": "o texto a enviar", "target": "(opc) chat_id destino (vazio = dono/canal atual)",
                   "channel": "(opc) canal: telegram (padrão)"}
    required = ("text",)

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        text = str(args.get("text") or "").strip()
        if not text:
            return ToolResult(False, "send_message exige 'text' não-vazio.", False)
        channel = str(args.get("channel") or "telegram").strip().lower()
        if channel != "telegram":
            return ToolResult(False, f"send_message só suporta telegram por enquanto (pediu '{channel}').", False)
        target = str(args.get("target") or "").strip()
        if not target:                                   # sem destino explícito → entrega ao DONO (hook do gateway)
            fn = getattr(ctx, "notify", None)
            if fn is None:
                return ToolResult(False, "sem 'target' e sem canal de dono neste contexto.", False)
            ok = bool(fn(text))
            return ToolResult(ok, "entregue ao dono" if ok else "falha ao entregar", effect=ok)
        cfg = getattr(ctx, "cfg", None)
        tg = ((cfg.get("channels") or {}).get("telegram") or {}) if isinstance(cfg, dict) else {}
        token = tg.get("token")
        if not token:
            return ToolResult(False, "sem token de Telegram (channels.telegram.token) p/ enviar a um target.", False)
        from okami.channels.telegram import TelegramChannel
        from okami.core.redact import redact
        try:
            TelegramChannel(token).send(target, text)
        except Exception as e:  # noqa: BLE001 — erro do vendor pode embutir o token → redige
            return ToolResult(False, f"falha ao enviar: {redact(str(e))[:200]}", False)
        return ToolResult(True, f"enviado p/ telegram:{target} ({len(text)} chars, sem LLM)", effect=True)
