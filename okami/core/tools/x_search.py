"""Tool x_search (#19) — busca no X/Twitter via Grok (xAI). Config-driven; sem config → indisponível."""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult, untrusted_wrap


class XSearch(Tool):
    name = "x_search"
    description = ("Busca no X/Twitter via Grok (xAI) com citações. Use p/ o que está sendo dito AGORA no "
                   "X sobre um tema/pessoa. Precisa de integrations.x configurado (api_key_env). Conteúdo "
                   "EXTERNO não-confiável.")
    args_schema = {"query": "a pergunta/tema a buscar no X", "handles": "(opc) lista de @perfis p/ restringir"}
    required = ("query",)

    def check(self) -> str | None:
        """Poda limpa sem integração configurada (senão o agente chama e leva RuntimeError em runtime)."""
        try:
            from okami.config import load_config
            from okami.integrations.x_search import x_config
            if x_config(load_config()) is None:
                return "X search não configurado — configure integrations.x.{api_key_env, model} no okami.yaml"
        except Exception:  # noqa: BLE001 — erro ao ler config não poda (fail-open)
            return None
        return None

    def run(self, args, ctx):
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult(False, "x_search: 'query' precisa ser uma string não-vazia.")
        from okami.core.redact import redact
        from okami.integrations.x_search import x_search
        try:
            res = x_search(getattr(ctx, "cfg", None), query, handles=args.get("handles") or None)
        except Exception as e:  # noqa: BLE001 — erro do vendor pode embutir a chave → redige sempre
            return ToolResult(False, f"x_search: {redact(str(e))[:200]}")
        cites = "\n".join(f"- {c}" for c in res.get("citations", [])[:10])
        body = res.get("answer", "") + (f"\n\nfontes:\n{cites}" if cites else "")
        return ToolResult(True, untrusted_wrap("x_search", body), effect=False)
