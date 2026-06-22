"""Tool session_search (pesquisa #6 item 10) — busca no histórico de TODAS as conversas/sessões.

Use quando precisar lembrar de algo conversado/decidido numa sessão passada (mesmo já compactada ou
arquivada por /new). É o complemento da memória: memória guarda PREFERÊNCIA durável; isto reabre o
HISTÓRICO de tarefa. Conteúdo é o transcript do PRÓPRIO agente (não é dado externo não-confiável).
"""
from __future__ import annotations

import time

from okami.core.tools.base import Tool, ToolResult


class SessionSearch(Tool):
    name = "session_search"
    description = ("Busca no histórico de TODAS as suas conversas passadas (transcripts de sessão, "
                   "inclusive arquivadas) — ex.: 'o que a gente decidiu sobre o banco no projeto X'. "
                   "É diferente de recall_memory (que guarda preferências/fatos duráveis): aqui você "
                   "relê o que foi DITO numa sessão. Devolve trechos com a sessão e o papel.")
    args_schema = {"query": "o que procurar no histórico", "limit": "(opc) nº de resultados (default 8)"}
    required = ("query",)

    def run(self, args, ctx):
        from okami.memory.session_search import search_sessions
        q = args.get("query")
        if not isinstance(q, str) or not q.strip():
            return ToolResult(False, "session_search: 'query' precisa ser uma string não-vazia.")
        try:
            limit = int(args.get("limit") or 8)
        except (TypeError, ValueError):
            limit = 8
        hits = search_sessions(ctx.home, q, max(1, min(limit, 20)))
        if not hits:
            return ToolResult(True, f"(nada no histórico de sessões casou com '{q}')", effect=False)
        lines = []
        for h in hits:
            when = ""
            if h.get("ts"):
                try:
                    when = time.strftime("%Y-%m-%d", time.localtime(float(h["ts"]))) + " "
                except (ValueError, OSError):
                    when = ""
            who = {"USER": "você", "AGENTE": "okami"}.get(h.get("role", ""), h.get("role", "?"))
            lines.append(f"[{when}sessão {h.get('chat_id', '?')} · {who}] "
                         f"{(h.get('snippet') or h.get('text', ''))[:160]}")
        return ToolResult(True, "\n".join(lines), effect=False)
