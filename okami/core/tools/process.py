"""Tools de processo em background (PTY/supervisor): start/write/poll/wait/log/list/kill/signal."""
from __future__ import annotations


from okami.core.tools.base import (
    Tool, ToolResult, _SENSITIVE_PATH,
)


class ProcessStart(Tool):
    name = "process_start"
    description = ("Roda um comando LONGO em BACKGROUND (não bloqueia o turno) → devolve um id. Use p/ "
                   "servidor que fica de pé, build/teste demorado, watch. Depois: process_poll/log/wait/kill.")
    args_schema = {"cmd": "comando a rodar em background",
                   "notify": "(opc) avisar no chat quando terminar (true/false)",
                   "watch": "(opc) lista de regex a vigiar no log (ex.: ['Listening on','ERROR'])",
                   "interactive": "(opc) PTY com stdin — use process_write p/ mandar input (true/false)"}
    required = ("cmd",)

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        from okami.core.sandbox import default_policy
        cmd = args["cmd"]
        if getattr(ctx, "remote", None) is not None:             # conectado a host remoto → process_start
            return ToolResult(False, "process_start roda em BACKGROUND LOCAL (sobe na máquina do dono, não "
                              "na remota). Estando conectado a um host, use run_shell com 'nohup … &' no "
                              "próprio remoto, ou remote_disconnect antes.", effect=False)
        policy = ctx.sandbox or default_policy()                 # #5: MESMA política do run_shell
        mode = getattr(policy, "mode", "")
        from okami.core import approval as _ap
        _hl = _ap.detect_hardline(cmd)
        if _hl:                                                  # HARDLINE (Hermes): incondicional, nem /yolo passa
            return ToolResult(False, f"🛑 BLOQUEADO (hardline): {_hl}. Catastrófico sem uso legítimo — "
                              f"recusado em QUALQUER modo. ({cmd[:80]})", effect=False)
        if mode == "read-only":                                  # processo longo é sempre efetivo → bloqueia
            return ToolResult(False, "sandbox read-only: process_start (comando longo) bloqueado.", effect=False)
        if mode != "yolo" and _SENSITIVE_PATH.search(cmd):       # P0.1: não exfiltra segredo nem em background
            return ToolResult(False, "sandbox: comando toca caminho sensível (.env/.ssh/.aws/credenciais/"
                              f"*.pem/*.key) — bloqueado. Use o perfil yolo se for de propósito. ({cmd[:80]})",
                              effect=False)
        watch = args.get("watch")
        if isinstance(watch, str):
            watch = [watch]
        try:
            meta = ProcessManager(ctx.workspace).start(
                cmd, policy, notify=bool(args.get("notify")), watch=watch,
                interactive=bool(args.get("interactive")))
        except ValueError as e:
            return ToolResult(False, str(e))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"falha ao iniciar processo: {e}")
        tag = " · interativo (process_write)" if meta.get("interactive") else ""
        return ToolResult(True, f"processo {meta['id']} no ar (pid {meta['pid']}, backend {meta.get('backend')}){tag}: "
                          f"{cmd[:80]}", effect=True)


class ProcessWrite(Tool):
    name = "process_write"
    description = ("Manda input p/ o stdin de um processo INTERATIVO (process_start interactive=true). "
                   "`submit` (default true) acrescenta Enter. Depois leia com process_log/process_poll.")
    args_schema = {"id": "id do processo", "data": "texto a enviar",
                   "submit": "(opc) acrescenta Enter (default true)"}
    required = ("id", "data")

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        submit = args.get("submit", True)
        ok = ProcessManager(ctx.workspace).write(args["id"], str(args.get("data", "")),
                                                 submit=bool(submit) if submit is not None else True)
        return ToolResult(ok, "input enviado" if ok else "processo não é interativo / não existe / já terminou",
                          effect=ok)


class ProcessPoll(Tool):
    name = "process_poll"
    description = "Status de um processo em background (running/exited + exit code) + saída recente."
    args_schema = {"id": "id do processo (de process_start)"}
    required = ("id",)

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        pm = ProcessManager(ctx.workspace)
        st = pm.poll(args["id"])
        body = f"status={st.get('status')}"
        if st.get("status") == "exited":
            body += f" exit={st.get('exit_code')}"
        tail = pm.log(args["id"], tail=1500)
        return ToolResult(st.get("status") != "unknown", body + (f"\n{tail}" if tail else ""))


class ProcessWait(Tool):
    name = "process_wait"
    description = "Espera um processo em background terminar (até `timeout`s) e devolve o status final + saída."
    args_schema = {"id": "id do processo", "timeout": "(opc) segundos (default 30)"}
    required = ("id",)

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        pm = ProcessManager(ctx.workspace)
        try:
            to = float(args.get("timeout", 30))
        except (TypeError, ValueError):
            to = 30.0
        st = pm.wait(args["id"], timeout=to)
        return ToolResult(st.get("status") != "unknown",
                          f"status={st.get('status')} exit={st.get('exit_code')}\n{pm.log(args['id'], tail=2000)}")


class ProcessLog(Tool):
    name = "process_log"
    description = ("Saída (log) de um processo em background — redigida e truncada. Paginação opcional: "
                   "`offset`/`limit` por linha (offset<0 conta do fim) p/ navegar log grande.")
    args_schema = {"id": "id do processo", "offset": "(opc) linha inicial (negativo = do fim)",
                   "limit": "(opc) nº de linhas (default tail completo)"}
    required = ("id",)

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        pm = ProcessManager(ctx.workspace)
        if "offset" in args or "limit" in args:                  # modo paginado
            try:
                off, lim = int(args.get("offset", 0)), int(args.get("limit", 200))
            except (TypeError, ValueError):
                off, lim = 0, 200
            page = pm.log_page(args["id"], offset=off, limit=lim)
            head = f"[linhas {page['offset']}–{page['offset'] + page['shown']} de {page['total']}]\n"
            return ToolResult(True, head + ("\n".join(page["lines"]) or "(sem saída ainda)"))
        return ToolResult(True, pm.log(args["id"]) or "(sem saída ainda)")


class ProcessList(Tool):
    name = "process_list"
    description = "Lista os processos em background (id, status, exit code) — registry de processos."

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        procs = ProcessManager(ctx.workspace).list()
        if not procs:
            return ToolResult(True, "(nenhum processo em background)")
        rows = [f"{p['id']} · {p.get('status')}"
                + (f" exit={p.get('exit_code')}" if p.get("status") == "exited" else "")
                + f" · {str(p.get('cmd', ''))[:60]}" for p in procs]
        return ToolResult(True, "\n".join(rows))


class ProcessKill(Tool):
    name = "process_kill"
    description = "Mata um processo em background (SIGTERM no grupo)."
    args_schema = {"id": "id do processo"}
    required = ("id",)

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        ok = ProcessManager(ctx.workspace).kill(args["id"])
        return ToolResult(ok, f"processo {args['id']} {'morto' if ok else 'não encontrado'}", effect=ok)


class ProcessSignal(Tool):
    name = "process_signal"
    description = ("Manda um sinal p/ um processo em background (lifecycle): TERM/INT/HUP/KILL/USR1/USR2/"
                  "CONT/STOP/QUIT. Ex.: HUP p/ recarregar, INT p/ Ctrl-C, USR1 p/ sinal custom.")
    args_schema = {"id": "id do processo", "signal": "nome do sinal (default TERM)"}
    required = ("id",)

    def run(self, args, ctx):
        from okami.core.processes import ProcessManager
        name = str(args.get("signal", "TERM"))
        ok = ProcessManager(ctx.workspace).signal(args["id"], name)
        return ToolResult(ok, f"sinal {name.upper()} → {args['id']}" if ok
                          else f"falhou (sinal inválido / processo inexistente): {name}", effect=ok)


# Tools terminais: o loop trata especialmente, mas elas existem para schema/parse.
