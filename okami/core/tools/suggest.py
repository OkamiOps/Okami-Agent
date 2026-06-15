"""Tool `suggest_automation` (#8 item 2) — o agente PROPÕE uma automação (não agenda).

Consent-first: nada roda sem o dono aceitar. O agente usa quando NOTA uma rotina ("você pede o resumo
do dia toda manhã") — a proposta entra na fila de sugestões; o dono aceita (`okami suggestions accept`)
e só então vira um cron job. O prompt é escaneado contra injeção (vai rodar depois sem ninguém olhando).
"""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolContext, ToolResult


class SuggestAutomation(Tool):
    name = "suggest_automation"
    description = ("PROPÕE (não agenda) uma automação recorrente p/ o dono aceitar, quando você nota uma "
                   "rotina dele. Consent-first: nada roda sem ele aceitar. schedule (cron/'30m'/'every 2h') "
                   "+ prompt (o que rodar). Use com parcimônia — só rotina real e útil.")
    args_schema = {"text": "por que sugere (1 frase, como você falaria)",
                   "schedule": "cron | '30m' | 'every 2h'",
                   "prompt": "o que a automação deve fazer quando disparar",
                   "dedup_key": "(opc) chave p/ não re-oferecer se o dono já dispensou"}
    required = ("text", "schedule", "prompt")
    terminal = False

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        text = str(args.get("text") or "").strip()
        schedule = str(args.get("schedule") or "").strip()
        prompt = str(args.get("prompt") or "").strip()
        if not (text and schedule and prompt):
            return ToolResult(False, "suggest_automation exige text + schedule + prompt.", False)
        from okami.skills.skill_security import Severity, scan_text   # o prompt roda depois, sem supervisão
        if any(f.severity >= Severity.HIGH for f in scan_text("suggestion", prompt)):
            return ToolResult(False, "prompt da automação bloqueado pelo scan de segurança (HIGH).", False)
        from okami.automation.suggestions import SuggestionStore
        store = SuggestionStore(ctx.workspace)
        sid = store.add(text=text, schedule=schedule, prompt=prompt,
                        dedup_key=str(args.get("dedup_key") or "").strip(), source="agent")
        if not sid:
            return ToolResult(False, "sugestão não registrada (já oferecida/dispensada antes, ou fila cheia "
                              "de pendentes).", False)
        return ToolResult(True, f"proposta registrada p/ o dono decidir: «{text}» (id {sid}). "
                          "Ele aceita com `okami suggestions accept {id}` ou dispensa — nada roda até lá.",
                          effect=True)
