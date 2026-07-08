"""Chat no terminal (REPL concorrente / TUI tela cheia)."""
from __future__ import annotations

import sys

import typer
from okami import __version__
from pathlib import Path
from okami.i18n import t as _tr
from okami.cli._app import app, console
from okami.cli._shared import (
    _resolve_agent,
)


def _make_redacting_history(path: str):
    """FileHistory que REDIGE segredo antes de gravar (M1): o usuário pode colar API_KEY=sk-… num prompt,
    e isso ia VERBATIM p/ ~/.okami/chat_history (plaintext). Agora passa pelo redact() (sk-/ghp_/Bearer/AKIA…)."""
    from prompt_toolkit.history import FileHistory

    from okami.core.redact import redact, safe_text

    class _RedactingFileHistory(FileHistory):
        def store_string(self, string: str) -> None:
            # safe_text antes: no Windows o buffer pode ter surrogate solitário → store_string estourava
            # ('surrogates not allowed') e crashava o REPL no Enter, ANTES mesmo de devolver a linha.
            super().store_string(redact(safe_text(string)))

    return _RedactingFileHistory(path)


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
    from okami.core.redact import safe_text
    if not sys.stdin.isatty():            # pipe/CI/sem terminal → REPL simples (prompt_toolkit travaria no /dev/tty)
        _run_repl_simple(ep, cid, console, tui, model_label=model_label, ctx_pct=ctx_pct)
        return
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.application import get_app
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.formatted_text import ANSI
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.patch_stdout import patch_stdout
    except Exception:  # noqa: BLE001 — sem prompt_toolkit: REPL simples garante o essencial
        _run_repl_simple(ep, cid, console, tui, model_label=model_label, ctx_pct=ctx_pct)
        return

    tui.install_focus_report_ignore()          # WIN1: ESC[I/ESC[O (iTerm2/Ghostty) não vazam pro buffer
    tui.install_bracketed_paste_timeout_patch()  # WIN2: paste colado sem ESC[201~ (SSH glitch) não trava input

    import collections
    import signal as _signal
    import threading
    import time as _t

    from okami.home import okami_home               # history do REPL é UI global → casa, NÃO o CWD
    hist_dir = okami_home()
    hist_dir.mkdir(parents=True, exist_ok=True)
    from okami import commands as _cmds              # autocomplete vem do REGISTRO declarativo
    cmds = _cmds.all_slash_names(scope="chat")

    # APROVAÇÃO por 1 TECLA (sem digitar /yes): quando há aprovação pendente E a linha está vazia,
    # y=sim · a/s=sempre · n=não resolvem na hora. Se já digitou algo, a tecla é normal (não atrapalha).
    _kb = KeyBindings()

    def _can_quickapprove() -> bool:
        try:
            return cid in ep._pending and not get_app().current_buffer.text.strip()
        except Exception:  # noqa: BLE001
            return False

    def _bind_key(key: str, cmd: str) -> None:
        @_kb.add(key, filter=Condition(_can_quickapprove))
        def _(event, _c=cmd):  # noqa: ANN001
            event.app.exit(result=_c)

    for _k, _c in (("y", "/yes"), ("Y", "/yes"), ("a", "/always"), ("s", "/always"), ("n", "/no"), ("N", "/no")):
        _bind_key(_k, _c)

    session = PromptSession(history=_make_redacting_history(str(hist_dir / "chat_history")),
                            completer=WordCompleter(cmds, sentence=True, ignore_case=True),
                            key_bindings=_kb, erase_when_done=True)   # apaga o eco cru → a fala vira moldura
    import shutil as _sh
    _ORANGE, _DIM, _RST = "\x1b[1;38;2;255;117;39m", "\x1b[38;2;61;62;80m", "\x1b[0m"

    def _prompt_msg():                            # barra de digitação FIXA embaixo (régua + ❯), estilo TUI/Hermes
        cols = _sh.get_terminal_size((80, 24)).columns
        return ANSI(f"{_DIM}{'─' * max(8, cols)}{_RST}\n{_ORANGE}❯{_RST} ")

    _placeholder = ANSI(f"{_DIM}{_tr('chat.placeholder', _default='talk to me…   / for commands · ^C cancel · ^D exit')}{_RST}")
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
                    console.print(f"[red]{_tr('chat.error', _default='error')}: {e}[/red]")
            _t.sleep(0.08)

    threading.Thread(target=_drain, daemon=True).start()

    _busy_since = [None]                          # quando o agente começou a pensar (p/ o elapsed ao vivo)

    def _usage_fragment() -> str:
        """'12K↑ 3K↓ · incluído' p/ o rodapé — mesma fonte do /usage. '' se nada contado ainda ou erro
        (custo é cosmético, nunca derruba o REPL)."""
        try:
            pc = ep.cfg.provider() if ep.cfg else None
            if pc is None:
                return ""
            return tui.usage_fragment(ep.store.entry(cid), transport=pc.transport,
                                      provider=ep.cfg.default_provider, model=pc.model)
        except Exception:  # noqa: BLE001
            return ""

    def _toolbar():
        if cid in ep._pending:                    # APROVAÇÃO pendente → barra BERRANTE (preto sobre amarelo)
            return ANSI("\x1b[1;30;43m " + _tr("chat.approval_bar",
                        _default="⚠ APPROVAL PENDING — press  [y] yes  ·  [a] always (stop asking)  ·  [n] no")
                        + "                                            \x1b[0m")
        try:
            pct, turns = ctx_pct(), len(ep.session(cid).history) // 2
        except Exception:  # noqa: BLE001
            pct, turns = 0, 0
        if _busy():                               # contador AO VIVO de quanto o agente está pensando (volta o elapsed)
            if _busy_since[0] is None:
                _busy_since[0] = _t.monotonic()
            live = getattr(ep, "_live_tool", None)   # tool RODANDO agora (setada pelo _on_event) → mostra
            if live and live.get("tool"):            # ela em vez de "thinking" genérico (paridade TUI)
                el = int(_t.monotonic() - live["t0"])
                prev = tui._args_preview(live.get("args") or {})
                state = f"{tui.tool_emoji(live['tool'])} {tui.tool_verb(live['tool'])}"
                if prev:
                    state += f" {prev}"
                state += f"  {el}s"
            else:
                state = (f"🧠 {_tr('chat.toolbar.thinking', _default='thinking')}  "
                         f"{int(_t.monotonic() - _busy_since[0])}s")
        else:
            _busy_since[0] = None
            state = "● " + _tr("chat.toolbar.ready", _default="ready")
        q = f"  ·  {len(inflight)} {_tr('chat.toolbar.queued', _default='queued')}" if inflight else ""
        usage = _usage_fragment()
        u = f"  ·  {usage}" if usage else ""
        return ANSI(f" {model_label}  ·  ctx {pct}%  ·  {turns} {_tr('status.turns', _default='turns')}  ·  {state}{q}{u}"
                    f"    {_tr('chat.toolbar.keys', _default='Ctrl-C cancel · Ctrl-D exit')} ")

    # WIN3: SIGWINCH (resize) + /redraw — repinta limpo quando o terminal fica com lixo (reflow, glitch de
    # multiplexador). Minimal: não reproduz o scrollback inteiro, só limpa e deixa o próximo prompt desenhar.
    _needs_redraw = [False]

    def _do_redraw() -> None:
        try:
            sys.stdout.write(tui.redraw_sequence())
            sys.stdout.flush()
        except Exception:  # noqa: BLE001 — repaint é cosmético, nunca derruba o REPL
            pass
        try:
            get_app().invalidate()
        except Exception:  # noqa: BLE001 — sem app rodando (fora do prompt()) → só o clear acima já ajuda
            pass

    def _on_winch(signum, frame) -> None:               # noqa: ANN001 — assinatura de signal handler
        _needs_redraw[0] = True

    if hasattr(_signal, "SIGWINCH"):
        try:
            _signal.signal(_signal.SIGWINCH, _on_winch)
        except (ValueError, OSError):                    # thread não-principal → sem handler; /redraw manual segue OK
            pass

    def _user_panel(msg: str):                        # fala do usuário em MOLDURA CIANO (simetria c/ o agente laranja)
        from datetime import datetime
        from rich.box import ROUNDED
        from rich.panel import Panel
        from rich.text import Text
        return Panel(Text(msg, style="#f4f4f8"),
                     title=f"[bold #00dfe8]● {_tr('chat.you', _default='you')}[/]", title_align="left",
                     subtitle=f"[dim]{datetime.now().strftime('%H:%M')}[/]", subtitle_align="right",
                     border_style="#00dfe8", box=ROUNDED, padding=(0, 1), expand=True)

    while True:
        if _needs_redraw[0]:                            # SIGWINCH pegou entre turnos → repinta ANTES do prompt
            _needs_redraw[0] = False
            _do_redraw()
        try:
            with patch_stdout(raw=True):                # erase_when_done (no PromptSession) apaga o eco cru
                line = session.prompt(_prompt_msg, bottom_toolbar=_toolbar, placeholder=_placeholder,
                                      refresh_interval=0.5)
        except EOFError:                                # Ctrl-D → sai
            break
        except KeyboardInterrupt:                       # Ctrl-C → cancela o turno, não sai
            if _busy():
                s = ep.sessions.get(cid)
                if s:
                    s.cancel = True
                console.print(f"[yellow]⏹ {_tr('chat.cancelling', _default='cancelling…')}[/yellow]")
            else:
                console.print(f"[dim]{_tr('chat.exit_hint', _default='Ctrl-D or /exit to quit')}[/dim]")
            continue
        line = safe_text(line)                          # Windows: limpa surrogate solitário (print/rota/LLM)
        if not (line and line.strip()):
            continue
        if line.strip().startswith("/"):                # comando: eco curto (não vira moldura de fala)
            console.print(f"[#00dfe8]❯[/] [dim]{line.strip()}[/]")
        else:                                           # fala do usuário → moldura ciano
            console.print(_user_panel(line.strip()))
        decision = _route_repl_line(line, busy=_busy(), pending_approval=cid in ep._pending,
                                    pending_clarify=cid in getattr(ep, "_clarify_pending", {}))
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
            from okami import prefs as _prefs                # M4: persiste a verbosidade → sobrevive ao restart
            _prefs.set_pref("repl_details", lv)
            console.print(f"[dim]🔎 {_tr('chat.details_set', _default='tool-call detail: {lv} (remembered)', lv=lv)}[/dim]")
            continue
        if decision == "agents":                        # cliente: painel de atividade
            sx = ep.sessions.get(cid)
            console.print(tui.activity_panel(bg=ep._bg, busy=_busy(), queued=len(sx.queued) if sx else 0,
                                             procs=ep.process_brief()))
            continue
        if decision == "replay":                        # M8: últimos tool-calls c/ args COMPLETOS + saída
            arg = line.split(maxsplit=1)[1].strip() if " " in line else ""
            try:
                n = max(1, min(int(arg), 60)) if arg else 10
            except ValueError:
                n = 10
            console.print(tui.replay_view(list(getattr(ep, "_step_log", []) or []), n))
            continue
        if decision == "redraw":                        # /redraw: repaint manual (paridade Ctrl+L do Hermes)
            _do_redraw()
            continue
        if decision in ("skin", "mouse"):               # só fazem sentido na TUI de tela cheia (--tui)
            console.print(f"[dim]🎨 {_tr('chat.tui_only', _default='{cmd} only works in the full-screen TUI (run `okami chat` without --no-tui).', cmd=decision)}[/dim]")
            continue
        if decision == "copy":                          # OSC-52: copia pro clipboard do terminal (passa por SSH/tmux)
            from okami.core.clipboard import copy_to_terminal, repl_copy_text
            arg = line.split(maxsplit=1)[1].strip() if " " in line else ""
            text, label = repl_copy_text(ep.session(cid).history, arg)
            if not text.strip():
                console.print(f"[dim]📋 {_tr('chat.copy_empty', _default='nothing to copy yet.')}[/dim]")
            else:
                copy_to_terminal(text)                   # emite a sequência OSC-52 no stdout
                console.print(f"[dim]📋 {_tr('chat.copied', _default='copied: {label} ({n} chars) — paste anywhere (works over SSH). /copy all = whole chat.', label=label, n=len(text))}[/dim]")
            continue
        if decision in ("handle", "queue"):             # toda fala vai pra fila → 1 só produtor (sem corrida)
            inflight.append(line)
            if decision == "queue":
                console.print(f"[dim]↩ {_tr('chat.queued_hint', _default='queued ({n}) — I will reply as soon as I finish', n=len(inflight))}[/dim]")
            continue
        ep.handle(cid, line)                            # approval | stop → direto (não inicia turno novo)
    stop.set()
    console.print(f"[dim]{_tr('chat.bye', _default='bye')} 🐺[/dim]")


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
            console.print(f"[dim]{_tr('chat.bye', _default='bye')} 🐺[/dim]")
            break
        from okami.core.redact import safe_text
        line = safe_text(line)                          # Windows: surrogate solitário estouraria print/LLM
        cmd = line.strip().lower()
        if cmd in ("/exit", "/quit", "exit", "quit", ":q"):
            console.print(f"[dim]{_tr('chat.bye', _default='bye')} 🐺[/dim]")
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
                console.print(f"[yellow]⏹ {_tr('chat.cancelling', _default='cancelling…')}[/yellow]")
                try:
                    _wait_for_turn(ep, cid)
                except KeyboardInterrupt:
                    pass
        last_elapsed = _time.time() - t0


@app.command(help=_tr("cli.chat", _default="Chat with the agent IN THE TERMINAL — no Telegram. The session persists (resumes when reopened)."))
def chat(
    message: str = typer.Argument(None, help=_tr("cli.chat.message", _default="Single message (-q/scripts mode). Empty = interactive REPL.")),
    agent: str = typer.Option(None, "-a", "--agent", help=_tr("cli.chat.agent", _default="Talk as an agent (agents/<id>).")),
    workspace: str = typer.Option("workspaces/default", "-w", "--workspace"),
    provider: str = typer.Option(None, "-p", "--provider"),
    model: str = typer.Option(None, "-m", "--model"),
    new: bool = typer.Option(False, "--new", help=_tr("cli.chat.new", _default="Start fresh (archives the previous terminal conversation).")),
    yolo: bool = typer.Option(False, "-y", "--yolo", help=_tr("cli.chat.yolo", _default="Auto-approve sensitive actions this session.")),
    use_tui: bool = typer.Option(False, "--tui/--no-tui",
                                 help=_tr("cli.chat.tui",
                                          _default="Line REPL (default — native terminal selection, Hermes-style). "
                                                   "--tui uses the full-screen Textual TUI (grabs the mouse: no native selection).")),
) -> None:
    """Conversa com o agente NO TERMINAL — sem Telegram. Sessão persiste (retoma ao reabrir).

    Por padrão usa o REPL de linha (prompt_toolkit, estilo Hermes/Claude-Code): o output imprime normal,
    então a SELEÇÃO e cópia NATIVA do terminal funcionam (arrasta + Cmd/Ctrl+C), com autocomplete na linha
    e status embaixo. --tui abre a TUI Textual de tela cheia (bonita, mas captura o mouse → sem seleção
    nativa). Slash commands (iguais ao Telegram — `/commands` lista tudo):
    /new /status /stop /background /title /model /think /usage /tools /sessions /resume /compact /persona
    /feedback /yolo /help. Saia com /exit ou Ctrl-D."""
    from okami.gateway import AgentEndpoint
    from okami.runner import run_task as _rt

    cfg, ws, name, home = _resolve_agent(agent, workspace)
    ws.mkdir(parents=True, exist_ok=True)

    # -p aceita ALIAS (sonnet/opus/codex/fast/smart/…), não só id cru — mesmo resolver do `okami
    # model`/`/model` (single source of truth, item (e) da precedência: flag > override de sessão).
    # -m sozinho só passa pelo resolver se for um alias CONHECIDO — senão segue cru (retrocompat: `-m
    # <bare-model-id>` sempre significou "modelo X no provider default", não deve virar erro de alias).
    from okami.llm.model_aliases import ALIASES, ModelAliasError, TIER_ALIASES, resolve as _resolve_model
    if provider:
        try:
            resolved_provider, resolved_model = _resolve_model(cfg, provider)
        except ModelAliasError as e:
            console.print(f"[red]✗ {e}[/red]")
            raise typer.Exit(1) from None
        provider = resolved_provider
        model = model or resolved_model           # -m explícito sempre vence o hint do alias
    elif model and model.strip().lower() in {*ALIASES, *TIER_ALIASES, *(k.lower() for k in cfg.model_aliases)}:
        try:
            provider, model = _resolve_model(cfg, model)
        except ModelAliasError as e:
            console.print(f"[red]✗ {e}[/red]")
            raise typer.Exit(1) from None

    def run_task(c, w, goal, **kw):                # honra -p/-m; mas /model da sessão (kw) vence
        kw.setdefault("agent_home", home)         # casa ISOLADA (memória/identidade) ≠ projeto onde mexe
        kw.setdefault("open_fs", True)            # CLI = DONO: alcança TODO o FS (relativo no CWD, absoluto livre)
        return _rt(c, w, goal, provider=kw.pop("provider", provider), model=kw.pop("model", model), **kw)

    mode = "yolo" if yolo else (cfg.approvals or {}).get("mode", "manual")
    cid = "terminal"

    if message:                                   # modo não-interativo (-q / pipe / script)
        from okami.channels.terminal import TerminalChannel
        ch = TerminalChannel(name, console=console)
        ep = AgentEndpoint(name, cfg, ws, ch, run_task=run_task, approval_mode=mode,
                           agent_home=home, open_fs=True)   # casa isolada + acesso a todo o FS (dono)
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
            console.print(f"[dim]({_tr('chat.tui_unavailable', _default='TUI unavailable: {e} — falling back to the REPL', e=e)})[/dim]")

    # --- fallback: REPL de linha (prompt_toolkit) -----------------------------
    import collections as _collections

    from okami.channels.terminal import TerminalChannel

    # COALESCE a exploração read-only (read/list/find) numa linha-resumo → ~10 linhas em vez de 150 (igual
    # Hermes). Em /details expanded mostra tudo; em collapsed (default) agrupa.
    _READ_TOOLS = {"read_file", "list_dir", "find_files"}
    _expl = {"n": 0, "ok": 0}
    _step_log = _collections.deque(maxlen=60)             # M8: buffer p/ /replay

    def _flush_expl() -> None:
        if _expl["n"]:
            fail = _expl["n"] - _expl["ok"]
            tail = f" · [red]{fail} ✗[/]" if fail else ""
            console.print("  🔎 [dim]"
                          + _tr("chat.explored", _default="explored {n} (read/list/find) — {ok} ok",
                                n=_expl["n"], ok=_expl["ok"])
                          + f"{tail}[/dim]")
            _expl["n"] = _expl["ok"] = 0

    ep._live_tool = {"tool": None, "args": None, "t0": None}   # tool RODANDO agora → o toolbar lê isto
    #   (mesma ideia do self._running da TUI, só que exposto no ep pq o toolbar mora em _run_repl)

    def _on_event(e: dict) -> None:               # progresso ao vivo: tool-calls, loop, compaction…
        import time as _time
        kind = e.get("kind")
        if kind == "tool_start":                  # anuncia ANTES de rodar → toolbar mostra ela viva
            ep._live_tool = {"tool": e.get("tool", ""), "args": e.get("args") or {}, "t0": _time.monotonic()}
            return
        secs = None
        if kind == "step":
            _step_log.append(e)                   # guarda TODO step (mesmo coalescido) p/ o /replay
            live = ep._live_tool
            if live.get("tool") == e.get("tool") and live.get("t0") is not None:
                secs = _time.monotonic() - live["t0"]   # duração medida no cliente (tool_start→step)
            ep._live_tool = {"tool": None, "args": None, "t0": None}
        if (kind == "step" and e.get("tool") in _READ_TOOLS
                and getattr(ep, "_details", "collapsed") == "collapsed"):
            _expl["n"] += 1
            _expl["ok"] += 1 if e.get("ok") else 0
            return                                # não imprime 1 linha por leitura — acumula
        _flush_expl()                             # qualquer outro evento → descarrega o resumo antes
        block = tui.tool_block(e, getattr(ep, "_details", "collapsed"), secs=secs)  # edit→diff, +tempo
        if block is not None:
            console.print(block)

    ch = TerminalChannel(name, console=console)
    ep = AgentEndpoint(name, cfg, ws, ch, run_task=run_task, approval_mode=mode, on_event=_on_event,
                       agent_home=home, open_fs=True,    # casa isolada + acesso a todo o FS (dono)
                       approval_timeout=600.0)        # REPL interativo: humano pode demorar p/ aprovar
    ep._step_log = _step_log                           # M8: o _run_repl lê isto p/ o /replay
    from okami import prefs as _prefs                  # M4: retoma a verbosidade lembrada (default collapsed)
    _saved_det = _prefs.get_pref("repl_details", "collapsed")
    ep._details = _saved_det if _saved_det in tui._DETAIL_LEVELS else "collapsed"
    if new:
        ep.session(cid).history.clear()
        ep.store.reset(cid)

    def _ctx_pct() -> int:
        used = sum(len(t) for _, t in ep.session(cid).history)
        return min(100, round(100 * used / ctx_budget))

    s = ep.session(cid)
    if sys.stdin.isatty() and sys.stdout.isatty():   # abre LIMPO (igual Hermes): limpa a tela ANTES do banner,
        console.clear()                              # sem poluir com o comando digitado/scrollback anterior.
    try:                                          # console Windows legacy (cp1252) não aguenta █ → fallback
        console.print(tui.welcome(version=__version__, model=model_label,
                                  provider=f"{cfg.default_provider} · {pc.tier}", cwd=Path.cwd(),
                                  session=session_id, agent=name, tools=tools, skills=sks,
                                  resumed=len(s.history) // 2))
    except Exception:  # noqa: BLE001
        console.print(f"[bold]Okami[/bold] · {name} · {model_label} [dim]({cfg.default_provider})[/dim] · "
                      f"{len(tools)} tools · {len(sks)} skills · /help")

    _run_repl(ep, cid, console, tui, model_label=model_label, ctx_pct=_ctx_pct)


