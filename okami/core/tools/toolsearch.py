"""tool_search — schema de tool SOB DEMANDA (pesquisa #5 item 27, paridade Hermes tool_search).

Quando há MUITAS tools (MCP numeroso), o prompt lista só 1 linha por tool; o schema completo
(descrição + args + obrigatórios) vem por aqui quando o agente precisa de detalhe.
"""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult


def _render(tool: Tool) -> str:
    args = "\n".join(f"    {k}: {v}" for k, v in (tool.args_schema or {}).items()) or "    (sem args)"
    req = ", ".join(tool.required) if tool.required else "—"
    return f"### {tool.name}\n{tool.description}\nargs:\n{args}\nobrigatórios: {req}"


class ToolSearch(Tool):
    name = "tool_search"
    description = ("Busca ferramentas por palavra-chave e devolve o SCHEMA COMPLETO (descrição, args, "
                   "obrigatórios). Use quando precisar dos detalhes de uma tool listada só pelo nome "
                   "(ex.: tools MCP resumidas no manual).")
    args_schema = {"query": "palavra-chave (nome ou parte da descrição)"}
    required = ("query",)

    def run(self, args, ctx):
        reg = getattr(ctx, "registry", None) or {}
        q = str(args.get("query", "")).strip().lower()
        if not q:
            return ToolResult(False, "tool_search exige 'query' não-vazio.")
        if not reg:
            return ToolResult(False, "tool_search indisponível neste contexto (sem registro).")
        scored: list[tuple[int, Tool]] = []
        for name, tool in reg.items():
            if name == self.name:
                continue
            hay_name, hay_desc = name.lower(), (tool.description or "").lower()
            if q == hay_name:
                scored.append((0, tool))
            elif q in hay_name:
                scored.append((1, tool))
            elif q in hay_desc:
                scored.append((2, tool))
        if not scored:
            names = ", ".join(sorted(n for n in reg if n != self.name))
            return ToolResult(False, f"nenhuma tool casa com '{q}'. Existem: {names}")
        scored.sort(key=lambda s: (s[0], s[1].name))
        body = "\n\n".join(_render(t) for _, t in scored[:5])
        more = len(scored) - 5
        if more > 0:
            body += f"\n\n(+{more} resultado(s) — refine a query)"
        return ToolResult(True, body, effect=False)
