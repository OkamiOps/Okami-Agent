"""Tools de memória/identidade: remember/recall/remember_user/finish_setup."""
from __future__ import annotations


from okami.core.tools.base import (
    Tool, ToolResult,
)


class RememberFact(Tool):
    name = "remember"
    description = "Guarda um fato durável na memória de longo prazo (decisões, preferências, etc.)."
    args_schema = {"text": "o fato a lembrar"}
    required = ("text",)

    def run(self, args, ctx):
        if ctx.memory is None:
            return ToolResult(False, "memória não ativa")
        from okami.memory.policy import prepare
        item = prepare(args.get("text", ""), source="agent")   # classifica + barra efêmero/trivial
        if item is None:
            return ToolResult(True, "(contexto efêmero/trivial — não guardei na memória de longo prazo)",
                              effect=False)
        ctx.memory.write(item)
        return ToolResult(True, f"lembrado [{item.kind}]: {item.text[:80]}", effect=True)


class RecallMemory(Tool):
    name = "recall_memory"
    description = "Busca na memória de longo prazo (fatos, decisões, trechos comprimidos)."
    args_schema = {"query": "o que buscar"}
    required = ("query",)

    def run(self, args, ctx):
        if ctx.memory is None:
            return ToolResult(False, "memória não ativa")
        items = ctx.memory.recall(args.get("query", ""), 5)
        if not items:
            return ToolResult(True, "(nada encontrado na memória)")
        from okami.memory.citation import cited_line       # cada hit vem com [categoria · origem · confiança]
        return ToolResult(True, "\n".join(cited_line(i) for i in items))


class RememberUser(Tool):
    name = "remember_user"
    description = "Anota algo durável SOBRE O USUÁRIO em USER.md (preferência, contexto) — sempre no prompt."
    args_schema = {"text": "o fato sobre o usuário"}
    required = ("text",)

    def run(self, args, ctx):
        from okami.memory import files as _f
        if not _f.append_user(ctx.home, args["text"]):    # CASA do agente (não o workspace/CWD); recusa segredo
            return ToolResult(True, "(não anotei — parece conter um segredo; não guardo isso no USER.md)",
                              effect=False)
        return ToolResult(True, f"USER.md += {args['text'][:80]}", effect=True)


class FinishSetup(Tool):
    name = "finish_setup"
    description = ("Encerra a CONFIGURAÇÃO INICIAL (gênese) do agente — chame SÓ na primeira conversa, "
                  "quando a pessoa estiver satisfeita com sua identidade (ou se ela quiser deixar p/ depois). "
                  "Em 'about_user', passe 1 linha sobre quem ela é (vai pro USER.md).")
    args_schema = {"about_user": "(opc) o que aprendeu sobre a pessoa, p/ o USER.md"}

    def run(self, args, ctx):
        from okami.memory import files as _f
        about = (args.get("about_user") or "").strip()
        if about:
            _f.append_user(ctx.home, about)               # identidade mora na CASA do agente
        marker = ctx.home / ".okami" / "genesis.done"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("done\n", encoding="utf-8")
        return ToolResult(True, "configuração inicial concluída ✓", effect=True)
