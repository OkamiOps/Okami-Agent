"""Tool `schedule_job` — a agente agenda tarefas sozinha (porta do cronjob_tools do Hermes).

"me lembra todo dia às 9h" não deve exigir o dono no terminal (okami cron add): a agente
cria o job na hora, do chat. UMA tool com `action` (create|list|pause|resume|remove) em vez
de 5 — schema enxuto no contexto (padrão Hermes contra inflar o prompt).

Segurança: o prompt do job roda DEPOIS, sem ninguém olhando → scan de injeção na criação
(mesmo scanner das skills). Usa Scheduler(".") — o MESMO store que o gateway tica.
"""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult

_ACTIONS = ("create", "list", "pause", "resume", "remove")


class ScheduleJob(Tool):
    name = "schedule_job"
    description = ("Agenda/gerencia tarefas recorrentes ou futuras (lembretes, rotinas). "
                   "action=create exige schedule ('30m', 'every 2h', cron '0 9 * * *', ou ISO) e "
                   "prompt (o que fazer quando disparar). Demais: list · pause/resume/remove (id). "
                   "Use quando a pessoa pedir lembrete/rotina — NÃO prometa 'vou te lembrar' sem criar o job.")
    args_schema = {"action": "create | list | pause | resume | remove",
                   "schedule": "(create) '30m' | 'every 2h' | cron | ISO-8601",
                   "prompt": "(create) o que executar/lembrar quando disparar",
                   "id": "(pause/resume/remove) id do job (veja action=list)"}
    required = ("action",)

    def run(self, args, ctx):
        from okami.automation.scheduler import Scheduler
        act = str(args.get("action") or "").strip().lower()
        if act not in _ACTIONS:
            return ToolResult(False, f"action '{act}' inválida — use: {' | '.join(_ACTIONS)}.", effect=False)
        sched = Scheduler(".")
        if act == "list":
            jobs = sched.load()
            if not jobs:
                return ToolResult(True, "(nenhum job agendado)", effect=False)
            lines = [f"• {j['id']} · {j['schedule']} · {'ativo' if j.get('enabled', True) else 'PAUSADO'}"
                     f" · {j['prompt'][:80]}" for j in jobs]
            return ToolResult(True, "\n".join(lines), effect=False)
        if act == "create":
            schedule = str(args.get("schedule") or "").strip()
            prompt = str(args.get("prompt") or "").strip()
            if not schedule or not prompt:
                return ToolResult(False, "create exige 'schedule' E 'prompt'.", effect=False)
            from okami.skills.skill_security import Severity, scan_text
            if any(f.severity >= Severity.HIGH for f in scan_text("cron-prompt", prompt)):
                return ToolResult(False, "prompt do job recusado: contém padrão de injeção/exfiltração "
                                  "(o job rodaria sozinho depois, sem ninguém olhando).", effect=False)
            try:
                job = sched.add(schedule, prompt)
            except Exception as e:  # noqa: BLE001 — schedule malformado etc.
                return ToolResult(False, f"não consegui agendar: {e}", effect=False)
            return ToolResult(True, f"agendado ✓ id={job['id']} · {job['schedule']} — confirme pra pessoa "
                              "O QUE e QUANDO ficou agendado.", effect=True)
        jid = str(args.get("id") or "").strip()
        if not jid:
            return ToolResult(False, f"{act} exige 'id' (veja action=list).", effect=False)
        if act == "remove":
            ok = sched.remove(jid)
            return ToolResult(ok, "removido ✓" if ok else f"job '{jid}' não existe.", effect=ok)
        try:
            sched.set_enabled(jid, act == "resume")
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"falhou: {e}", effect=False)
        return ToolResult(True, ("retomado ✓" if act == "resume" else "pausado ✓") + f" ({jid})", effect=True)
