"""Tools de OPERAÇÃO da máquina — pra o agente se virar sozinho numa VPS 24/7:
  - system_monitor: saúde do host (disco/RAM/CPU/load/uptime) → checar recurso antes de tarefa pesada,
    diagnosticar lentidão, decidir adiar/limpar;
  - restart_gateway: reiniciar o PRÓPRIO gateway (pega código/config novos, recupera de estado ruim).
"""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult


class SystemMonitor(Tool):
    name = "system_monitor"
    description = (
        "Mostra a saúde da MÁQUINA (host) onde você roda: disco livre, RAM, CPU/load, uptime, nº de "
        "processos. Use ANTES de uma tarefa pesada (build/transcrição/vídeo) pra ver se a VPS tem recurso, "
        "ou pra diagnosticar lentidão. Traz alertas (disco/RAM/cpu altos) p/ você decidir adiar ou limpar."
    )
    args_schema = {"what": "(opc) all | disk | mem | cpu | load (default all)"}
    required = ()

    def run(self, args, ctx):
        from okami.core import sysmon
        path = str(getattr(ctx, "workspace", ".") or ".")
        stats = sysmon.host_stats(path)
        if not stats:
            return ToolResult(False, "não consegui ler as métricas do host.", effect=False)
        what = str(args.get("what") or "all").strip().lower()
        _alias = {"mem": "memory"}
        if what not in ("all", ""):
            key = _alias.get(what, what)
            stats = {key: stats.get(key)} if key in stats else stats
        flags = sysmon.health_flags(stats)
        lines = []
        d = stats.get("disk")
        if d:
            lines.append(f"💾 disco: {d['free_gb']} GB livres de {d['total_gb']} GB ({d['used_pct']}% usado)")
        m = stats.get("memory")
        if m:
            lines.append(f"🧠 RAM: {m['available_gb']} GB livres de {m['total_gb']} GB ({m['used_pct']}% usado)")
        c = stats.get("cpu")
        if c:
            lines.append(f"⚙️ CPU: {c.get('percent', '?')}% · {c.get('cores', '?')} cores")
        if stats.get("load"):
            lines.append(f"📈 load (1/5/15m): {stats['load']}")
        if stats.get("uptime_h") is not None:
            lines.append(f"⏱ uptime: {stats['uptime_h']} h · {stats.get('processes', '?')} processos")
        body = "\n".join(lines) or str(stats)
        if flags:
            body += "\n" + "\n".join(flags)
        return ToolResult(True, body, effect=False, content=stats)


class RestartGateway(Tool):
    name = "restart_gateway"
    description = (
        "Reinicia o PRÓPRIO gateway (pega o código/config mais novos, recupera de um estado ruim). Só "
        "funciona se você está rodando em background gerenciado (serviço systemd/launchd ou `okami gateway "
        "start`). DISRUPTIVO: a sessão atual reinicia — use quando precisar mesmo (dep nova, config nova, "
        "loop ruim), não à toa."
    )
    args_schema = {}
    required = ()

    def run(self, args, ctx):
        from okami.gateway.restart import schedule_self_restart
        ok, msg = schedule_self_restart()
        return ToolResult(ok, msg, effect=ok)
