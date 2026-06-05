"""Chat no terminal (REPL concorrente / TUI tela cheia)."""
from __future__ import annotations

import sys

import typer
from okami import __version__
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _resolve_agent,
)


def _wait_for_turn(ep, cid: str, poll: float = 0.05) -> None:
    """Bloqueia o REPL até a tarefa terminar — ou até o agente PEDIR aprovação (vira o próximo input)."""
    import time as _t
    s = ep.sessions.get(cid)
    while s and s.busy and cid not in ep._pending:
        _t.sleep(poll)


from okami.tui import _route_repl_line  # roteamento puro do chat (REPL + TUI compartilham)  # noqa: E402


def _run_repl(ep, cid, console, tui, *, model_label: str, ctx_pct) -> None:
    """REPL CONCORRENTE (estilo Hermes/Claude-Code): você digita ENQUANTO o agente trabalha; a
    aprovação go/no-go é respondível na hora; mensagens novas entram numa FILA e rodam em ordem;
    Ctrl-C cancela o turno (NÃO sai), Ctrl-D sai. Sem prompt_toolkit → cai no REPL simples (bloqueante),
    pra nunca quebrar o básico. O ponto-chave é o `patch_stdout`: o progresso ao vivo do agente não
    corrompe a linha que você está digitando (o que faz o terminal sentir 'perfeito')."""
    if not sys.stdin.isatty():            # pipe/CI/sem terminal → REPL simples (prompt_toolkit travaria no /dev/tty)
        _run_repl_simple(ep, cid, console, tui, model_label=model_label, ctx_pct=ctx_pct)
        return
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.formatted_text import ANSI
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.patch_stdout import patch_stdout
    except Exception:  # noqa: BLE001 — sem prompt_toolkit: REPL simples garante o essencial
        _run_repl_simple(ep, cid, console, tui, model_label=model_label, ctx_pct=ctx_pct)
        return

    import collections
    import threading
    import time as _t

    from okami.home import okami_home               # history do REPL é UI global → casa, NÃO o CWD
    hist_dir = okami_home()
    hist_dir.mkdir(parents=True, exist_ok=True)
    from okami import commands as _cmds              # autocomplete vem do REGISTRO declarativo
    cmds = _cmds.all_slash_names(scope="chat")
    session = PromptSession(history=FileHistory(str(hist_dir / "chat_history")),
                            completer=WordCompleter(cmds, sentence=True, ignore_case=True))
    prompt_fmt = ANSI("\x1b[1;38;2;255;117;39m›\x1b[0m ")
    inflight: "collections.deque[str]" = collections.deque()   # digitado enquanto ocupado (FIFO)
    stop = threading.Event()

    def _busy() -> bool:
        s = ep.sessions.get(cid)
        return bool(s and s.busy)

    def _drain() -> None:
        """ÚNICO produtor de turnos: tira da fila quando o agente fica livre → sem corrida."""
        while not stop.is_set():
            if inflight and not _busy() and cid not in ep._pending:
                try:
                    ep.handle(cid, inflight.popleft())
                except Exception as e:  # noqa: BLE001 — um turno que falha não derruba o REPL
                    console.print(f"[red]erro: {e}[/red]")
            _t.sleep(0.08)

    threading.Thread(target=_drain, daemon=True).start()

    def _toolbar():
        try:
            pct, turns = ctx_pct(), len(ep.session(cid).history) // 2
        except Exception:  # noqa: BLE001
            pct, turns = 0, 0
        state = ("🧠 pensando" if _busy()
                 else "✍ responda a aprovação" if cid in ep._pending else "● pronto")
        q = f"  ·  {len(inflight)} na fila" if inflight else ""
        return ANSI(f" {model_label}  ·  ctx {pct}%  ·  {turns} trocas  ·  {state}{q}"
                    "    Ctrl-C cancela · Ctrl-D sai ")

    while True:
        try:
            with patch_stdout(raw=True):
                line = session.prompt(prompt_fmt, bottom_toolbar=_toolbar, refresh_interval=0.5)
        except EOFError:                                # Ctrl-D → sai
            break
        except KeyboardInterrupt:                       # Ctrl-C → cancela o turno, não sai
            if _busy():
                s = ep.sessions.get(cid)
                if s:
                    s.cancel = True
                console.print("[yellow]⏹ cancelando…[/yellow]")
            else:
                console.print("[dim]Ctrl-D ou /exit p/ sair[/dim]")
            continue
        if not (line and line.strip()):
            continue
        decision = _route_repl_line(line, busy=_busy(), pending_approval=cid in ep._pending)
        if decision == "exit":
            break
        if decision == "help":
            console.print(tui.help_table())
            continue
        if decision == "details":                       # cliente: verbosidade dos tool-calls
            arg = line.split(maxsplit=1)[1].strip().lower() if " " in line else ""
            lv = getattr(ep, "_details", "collapsed")
            if arg in tui._DETAIL_LEVELS:
                lv = arg
            else:                                       # sem arg → cicla
                lv = tui._DETAIL_LEVELS[(tui._DETAIL_LEVELS.index(lv) + 1) % len(tui._DETAIL_LEVELS)]
            ep._details = lv
            console.print(f"[dim]🔎 detalhes dos tool-calls: {lv}[/dim]")
            continue
        if decision == "agents":                        # cliente: painel de atividade
            sx = ep.sessions.get(cid)
            console.print(tui.activity_panel(bg=ep._bg, busy=_busy(), queued=len(sx.queued) if sx else 0,
                                             procs=ep.process_brief()))
            continue
        if decision in ("skin", "mouse"):               # só fazem sentido na TUI de tela cheia (--tui)
            console.print(f"[dim]🎨 {decision} só vale na TUI de tela cheia (rode `okami chat` sem --no-tui).[/dim]")
            continue
        if decision in ("handle", "queue"):             # toda fala vai pra fila → 1 só produtor (sem corrida)
            inflight.append(line)
            if decision == "queue":
                console.print(f"[dim]↩ na fila ({len(inflight)}) — respondo assim que terminar[/dim]")
            continue
        ep.handle(cid, line)                            # approval | stop → direto (não inicia turno novo)
    stop.set()
    console.print("[dim]tchau 🐺[/dim]")


def _run_repl_simple(ep, cid, console, tui, *, model_label: str, ctx_pct) -> None:
    """Fallback bloqueante (sem prompt_toolkit): 1 turno por vez, status-bar impressa a cada prompt."""
    import time as _time
    last_elapsed = 0.0
    while True:
        try:
            console.print(tui.status_bar(model=model_label, ctx_pct=ctx_pct(),
                                         turns=len(ep.session(cid).history) // 2, elapsed=last_elapsed))
        except Exception:  # noqa: BLE001 — console legacy: segue sem a barra
            pass
        try:
            line = console.input("[bold #ff7527]›[/bold #ff7527] ")
        except (EOFError, KeyboardInterrupt):
            console.print("[dim]tchau 🐺[/dim]")
            break
        cmd = line.strip().lower()
        if cmd in ("/exit", "/quit", "exit", "quit", ":q"):
            console.print("[dim]tchau 🐺[/dim]")
            break
        if cmd == "/help":
            console.print(tui.help_table())
            continue
        t0 = _time.time()
        ep.handle(cid, line)
        try:
            _wait_for_turn(ep, cid)
        except KeyboardInterrupt:                       # Ctrl-C durante o turno = aborta (não sai)
            s = ep.sessions.get(cid)
            if s and s.busy:
                s.cancel = True
                console.print("[yellow]⏹ cancelando…[/yellow]")
                try:
                    _wait_for_turn(ep, cid)
                except KeyboardInterrupt:
                    pass
        last_elapsed = _time.time() - t0


@app.command()
def chat(
    message: str = typer.Argument(None, help="Mensagem única (modo -q/scripts). Vazio = REPL interativo."),
    agent: str = typer.Option(None, "-a", "--agent", help="Conversa como um agente (agents/<id>)."),
    workspace: str = typer.Option("workspaces/default", "-w", "--workspace"),
    provider: str = typer.Option(None, "-p", "--provider"),
    model: str = typer.Option(None, "-m", "--model"),
    new: bool = typer.Option(False, "--new", help="Começa do zero (arquiva a conversa anterior do terminal)."),
    yolo: bool = typer.Option(False, "-y", "--yolo", help="Auto-aprova ações sensíveis nesta sessão."),
    use_tui: bool = typer.Option(True, "--tui/--no-tui",
                                 help="TUI de tela cheia (default). --no-tui usa o REPL de linha."),
) -> None:
    """Conversa com o agente NO TERMINAL — sem Telegram. Sessão persiste (retoma ao reabrir).

    Por padrão abre a TUI de tela cheia (regiões fixas, mouse, scroll, status pinado, aprovação por
    botão). Use --no-tui pro REPL de linha. Slash commands (iguais ao Telegram — `/commands` lista tudo):
    /new /status /stop /background /title /model /think /usage /tools /sessions /resume /compact /persona
    /feedback /yolo /help. Saia com /exit ou Ctrl-D."""
    from okami.gateway import AgentEndpoint
    from okami.runner import run_task as _rt

    cfg, ws, name = _resolve_agent(agent, workspace)
    ws.mkdir(parents=True, exist_ok=True)

    def run_task(c, w, goal, **kw):                # honra -p/-m; mas /model da sessão (kw) vence
        return _rt(c, w, goal, provider=kw.pop("provider", provider), model=kw.pop("model", model), **kw)

    mode = "yolo" if yolo else (cfg.approvals or {}).get("mode", "manual")
    cid = "terminal"

    if message:                                   # modo não-interativo (-q / pipe / script)
        from okami.channels.terminal import TerminalChannel
        ch = TerminalChannel(name, console=console)
        ep = AgentEndpoint(name, cfg, ws, ch, run_task=run_task, approval_mode=mode)
        if new:
            ep.session(cid).history.clear()
            ep.store.reset(cid)
        ep.handle(cid, message)
        _wait_for_turn(ep, cid)
        return

    # --- parâmetros de exibição (TUI e REPL compartilham) ---------------------
    from datetime import datetime

    from okami import tui
    from okami import skills as skillmod
    from okami.core.tools import default_registry
    from okami.llm.providers import context_window_tokens

    pc = cfg.provider()
    model_label = model or pc.model
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    tools = list(default_registry().keys())
    try:
        from okami.home import skills_dir
        sks = skillmod.load_skills(skills_dir())
    except Exception:  # noqa: BLE001 — sem skills não impede o chat
        sks = []
    ctx_budget = max(1, int(context_window_tokens(pc) * pc.chars_per_token))

    # --- TUI de tela cheia (default, quando há terminal real) -----------------
    if use_tui and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            from okami.tui_app import run_chat_tui
            if run_chat_tui(cfg=cfg, ws=ws, name=name, cid=cid, run_task=run_task, approval_mode=mode,
                            model_label=model_label, provider_label=f"{cfg.default_provider} · {pc.tier}",
                            ctx_budget=ctx_budget, agent=name, session_id=session_id, tools=tools,
                            skills=sks, version=__version__, new=new):
                return
        except Exception as e:  # noqa: BLE001 — TUI falhou? cai no REPL, nunca deixa o usuário na mão
            console.print(f"[dim](TUI indisponível: {e} — caindo no REPL)[/dim]")

    # --- fallback: REPL de linha (prompt_toolkit) -----------------------------
    from okami.channels.terminal import TerminalChannel

    def _on_event(e: dict) -> None:               # progresso ao vivo: tool-calls, loop, compaction…
        line = tui.event_line(e, getattr(ep, "_details", "collapsed"))
        if line is not None:
            console.print(line)

    ch = TerminalChannel(name, console=console)
    ep = AgentEndpoint(name, cfg, ws, ch, run_task=run_task, approval_mode=mode, on_event=_on_event,
                       approval_timeout=600.0)        # REPL interativo: humano pode demorar p/ aprovar
    ep._details = "collapsed"                         # verbosidade dos tool-calls (/details) — estado do cliente
    if new:
        ep.session(cid).history.clear()
        ep.store.reset(cid)

    def _ctx_pct() -> int:
        used = sum(len(t) for _, t in ep.session(cid).history)
        return min(100, round(100 * used / ctx_budget))

    s = ep.session(cid)
    try:                                          # console Windows legacy (cp1252) não aguenta █ → fallback
        console.print(tui.welcome(version=__version__, model=model_label,
                                  provider=f"{cfg.default_provider} · {pc.tier}", cwd=Path.cwd(),
                                  session=session_id, agent=name, tools=tools, skills=sks,
                                  resumed=len(s.history) // 2))
    except Exception:  # noqa: BLE001
        console.print(f"[bold]Okami[/bold] · {name} · {model_label} [dim]({cfg.default_provider})[/dim] · "
                      f"{len(tools)} tools · {len(sks)} skills · /help")

    _run_repl(ep, cid, console, tui, model_label=model_label, ctx_pct=_ctx_pct)


