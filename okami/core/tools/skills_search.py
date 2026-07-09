"""Tool search_skills — DESCOBRE skills no catálogo GitHub confiável ANTES de instalar.

Fecha o gap real do incidente "gog": o agente só tinha `install_skill`, que exige um `owner/repo`
já em mãos. Sem forma de DESCOBRIR o que existe, ele inventava fonte ou improvisava um workaround
inseguro (vasculhar credencial no disco) quando faltava capacidade (ex.: Gmail). Agora o agente
busca primeiro (`search_skills`), vê name/description/source/trust dos candidatos reais, e só então
chama `install_skill(source=.., name=only)` — a pipeline de instalação (quarentena + scan + matriz
confiança×verdict + lockfile) não muda uma linha; esta tool só lê o índice (okami/skills/registry.py).
"""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult


class SearchSkills(Tool):
    name = "search_skills"
    description = ("BUSCA no catálogo de skills disponíveis (taps GitHub confiáveis) ANTES de tentar "
                   "instalar uma sem saber a fonte certa. Use quando a tarefa precisa de uma capacidade "
                   "que você não tem (ex.: 'preciso de algo pra Gmail') e você NÃO sabe o owner/repo — "
                   "NUNCA invente uma fonte nem improvise workaround inseguro. Devolve candidatos com "
                   "name/description/source(owner/repo)/trust; passe `source` (e `name`, se indicado) "
                   "pro install_skill. Sem query, lista as skills mais conhecidas (browse).")
    args_schema = {"query": "(opc) o que procurar (ex.: 'gmail', 'pdf'); vazio = browse geral",
                   "limit": "(opc) nº de resultados (default 10)"}
    required = ()

    def run(self, args, ctx):
        from okami.skills.registry import default_source

        query = str(args.get("query") or "").strip()
        try:
            limit = int(args.get("limit") or 10)
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(limit, 30))

        src = default_source()
        try:
            cands = src.search(query, limit) if query else src.browse(limit)
        except Exception as e:  # noqa: BLE001 — descoberta nunca deve travar o loop do agente
            return ToolResult(False, f"search_skills: falha ao consultar o catálogo ({e}).")

        if not cands:
            hint = f" p/ '{query}'" if query else ""
            return ToolResult(True, f"(nenhuma skill encontrada{hint} nos taps confiáveis — "
                              "considere `okami skill tap github <org>` p/ ampliar, ou instale por URL/"
                              "caminho local se você já confia na fonte)", effect=False)

        lines = [f"{len(cands)} skill(s) encontrada(s):"]
        for c in cands:
            only_hint = f" · instale com name=\"{c.only}\"" if c.only and c.only != c.name else ""
            lines.append(f"  • [{c.trust}] {c.name} — {c.description[:100]} "
                         f"(source=\"{c.source}\"{only_hint})")
        return ToolResult(True, "\n".join(lines), effect=False)
