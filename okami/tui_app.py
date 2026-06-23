"""TUI de tela cheia do `okami chat` (Textual) — o terminal "profissional" (não-garagem).

Diferença pro REPL de linha: aqui é uma ÁRVORE DE COMPONENTES com regiões FIXAS — header · log
rolável · barra de aprovação · input · status. A ENTRADA é estruturalmente separada da SAÍDA, então
a linha que você digita NUNCA é corrompida por output ao vivo (a dor #1 do terminal antigo). De graça
vêm: scroll, mouse, resize, status pinado embaixo. (Mesma ideia do Ink do Hermes / pi-tui do OpenClaw,
mas em Python via Textual.)

Concorrência sem deadlock: um ÚNICO worker thread chama `ep.handle` (roteia/enfileira/drena); a UI só
enfileira input e desenha. Todo update de widget vindo de thread de fundo passa por `call_from_thread`.
O turno do agente roda em thread própria (ep._spawn) e fala com a tela via o `TuiChannel`. Aprovação
go/no-go vira BOTÃO inline (Aprovar/Negar), respondível na hora, sem digitar /yes.

Sem textual instalado → `run_chat_tui` devolve False e o `okami chat` cai no REPL prompt_toolkit.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from pathlib import Path

from okami.channels.base import Channel
from okami import tui as _tui
from okami.tui import _route_repl_line

# --- /skin persistente (prefs.json em $OKAMI_HOME) -----------------------------
# Best-effort: prefs e cosmético, NUNCA deve quebrar a TUI (env/IO corrompido → default).
from okami.home import okami_home as _okami_home


def _PREFS_PATH():
    return _okami_home() / "prefs.json"


# M3: tema e /details agora moram no MESMO prefs.json, via okami.prefs (fonte única, merge-safe, atômico).
# tui_app não duplica mais o read/write — só delega a chave 'theme'. (Era a duplicação que o achado M3 criticava.)
def _load_theme(default="okami"):
    """Tema persistido (prefs unificado), ou `default` se ausente/inválido. NUNCA levanta."""
    from okami import prefs
    v = prefs.get_pref("theme", default)
    return v if isinstance(v, str) and v else default


def _save_theme(name):
    """Persiste o tema no prefs unificado (merge — preserva repl_details etc.). True se salvou."""
    if not isinstance(name, str) or not name:
        return False
    from okami import prefs
    return prefs.set_pref("theme", name)


try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal
    from textual.suggester import SuggestFromList
    from textual.widgets import Button, Input, OptionList, RichLog, Static
    from textual.widgets.option_list import Option
    _HAS_TEXTUAL = True
except Exception:  # noqa: BLE001 — sem textual: o chamador cai no REPL
    _HAS_TEXTUAL = False

# Prefixos que ENVOLVEM uma resposta do agente vs. notificações de sistema de 1 linha (espelha o
# TerminalChannel pra renderização consistente entre REPL e TUI).
_REPLY_MARKS = {"✅", "⚠", "❌", "❓"}
_SYS_MARKS = {"💭", "🧠", "🧬", "🎨", "🎭", "⏰", "↻", "🧹", "⏹", "⚡", "🔒", "🚫", "🔊", "▶", "·"}
_SYS_COLOR = {"💭": "dim", "🧠": "dim", "🧬": "magenta", "🎨": "magenta", "🎭": "magenta", "⏰": "blue",
              "↻": "blue", "🧹": "dim", "⏹": "yellow", "⚡": "yellow", "🔒": "dim", "🚫": "red",
              "🔊": "cyan", "▶": "dim", "·": "dim", "✅": "green", "⚠": "yellow", "❌": "red", "❓": "cyan"}
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class TuiChannel(Channel):
    """Canal que entrega `send()` pra árvore Textual (thread-safe via call_from_thread)."""

    name = "terminal"

    def __init__(self, app: "OkamiChatApp", *, allow_chats=None):
        self.app = app
        self.sent: list[tuple[str, str]] = []
        self.allow_chats = allow_chats

    def send(self, chat_id, text: str) -> None:
        self.sent.append((str(chat_id), text))
        self.app.call_from_thread(self.app.sink_message, str(chat_id), text)

    def send_approval(self, chat_id, text: str, nonce: str = "") -> None:
        # go/no-go → abre o PAINEL na hora (com a ação), em vez do texto "(/yes ou /no)" no log.
        self.app.call_from_thread(self.app.show_approval, text)

    def send_audio(self, chat_id, audio_path) -> None:
        self.app.call_from_thread(self.app.sink_note, f"🔊 áudio: {audio_path}")

    def poll(self):
        return []

    def allowed(self, chat_id) -> bool:
        return self.allow_chats is None or str(chat_id) in {str(c) for c in self.allow_chats}


def _render_message(text: str):
    """str (com prefixo do AgentEndpoint) → renderable do Rich (Markdown p/ fala, Text colorido p/ sistema)."""
    from rich.markdown import Markdown
    from rich.text import Text
    head = text[:1]
    is_reply = head in _REPLY_MARKS or head not in _SYS_MARKS
    if is_reply:
        body = text[1:].strip() if head in _REPLY_MARKS else text
        return Markdown(body) if body.strip() else Text("")
    return Text(text, style=_SYS_COLOR.get(head, ""))


if _HAS_TEXTUAL:

    from textual.theme import Theme

    OKAMI_THEME = Theme(                                  # tema da marca (default do /skin)
        name="okami", primary="#ff7527", secondary="#ff39d1", accent="#00dfe8",
        foreground="#f4f4f8", background="#0d0d12", surface="#16161f", panel="#221a12",
        success="#1f7a3d", warning="#ffb86c", error="#7a2a2a", dark=True,
    )

    class OkamiChatApp(App):
        """App Textual do chat: header · log · aprovação · input · status."""

        # CSS em VARIÁVEIS de tema ($surface/$primary/…) → /skin troca o tema e a chrome re-tematiza.
        CSS = """
        Screen { layout: vertical; background: $background; }
        #header { height: 1; padding: 0 1; background: $surface; }
        #log { height: 1fr; padding: 1 2; background: $background; scrollbar-color: $primary; scrollbar-size: 1 1; }
        #activity { height: auto; display: none; padding: 0 2; }
        #cmdmenu { height: auto; max-height: 14; display: none; background: $panel; border-top: solid $accent;
                   scrollbar-size: 1 1; }
        #cmdmenu:focus { border-top: solid $accent; }
        #approval { height: auto; display: none; padding: 1 2; background: $panel; border-top: solid $primary; }
        #approval-label { width: 1fr; content-align: left middle; color: $warning; }
        #input { border: round $panel; background: $surface; }
        #input:focus { border: round $accent; }
        #status { height: 1; padding: 0 1; color: $text-muted; background: $surface; }
        Button { min-width: 12; margin: 0 1; }
        Button#approve { background: $success; }
        Button#always { background: $warning; }
        Button#deny { background: $error; }
        """

        BINDINGS = [
            Binding("ctrl+d", "ctrl_d", "sair (2x p/ confirmar)", priority=True),
            Binding("ctrl+c", "ctrl_c", "cancelar/sair", priority=True, show=False),
            Binding("ctrl+l", "clear_log", "limpar"),
        ]

        def __init__(self, *, cfg, ws, name, cid, run_task, approval_mode="manual",
                     model_label="", provider_label="", ctx_budget=200_000, agent="okami",
                     session_id="", tools=None, skills=None, version="", new=False, spawn=None,
                     on_started=None):
            super().__init__()
            from okami.gateway import AgentEndpoint
            try:                                          # registra o tema da marca (senao self.theme="okami" cai no default textual)
                self.register_theme(OKAMI_THEME)
            except Exception:  # noqa: BLE001 — Textual ja tem? beleza, segue
                pass
            self._cid = cid
            self._model_label = model_label
            self._provider_label = provider_label
            self._ctx_budget = max(1, int(ctx_budget))
            self._agent = agent
            self._session_id = session_id
            self._tools = tools or []
            self._skills = skills or []
            self._version = version
            self._new = new
            self._on_started = on_started
            self.channel = TuiChannel(self)
            self.ep = AgentEndpoint(name, cfg, ws, self.channel, run_task=run_task,
                                    approval_mode=approval_mode, on_event=self._event_from_thread,
                                    spawn=spawn, approval_timeout=600.0)   # humano no terminal pode demorar
            self.inflight: deque[str] = deque()
            self._input_q: queue.Queue[str] = queue.Queue()
            self._stop = threading.Event()
            self._spin = 0
            self._exit_armed = 0.0
            self._busy_since: float | None = None
            self._details = "collapsed"                   # verbosidade dos tool-calls (/details)
            self._running: tuple | None = None            # tool RODANDO agora (tool, args, t0) → indicador vivo
            self._ticks = 0                               # contador monotônico de ticks (verbo rotativo)
            self._history = _tui.InputHistory()           # ↑/↓ recall das mensagens enviadas
            try:                                          # tema persistido de sessoes anteriores (/skin save)
                saved = _load_theme()
                if saved and saved in self.available_themes:
                    self.theme = saved                   # Textual re-tematiza a chrome no startup (incl. "okami")
            except Exception:  # noqa: BLE001 — prefs ausentes/invalidos: fica no default
                pass
            self._mouse_on = True                         # DEFAULT ON: mouse capturado (clique no autocomplete/
            #   botões) E seleção do Textual funciona junto — arraste seleciona e SOLTA já copia (on_mouse_up)
            self.transcript: list[tuple[str, str]] = []   # (kind, text) p/ teste

        # ---- layout ----------------------------------------------------------
        def compose(self) -> "ComposeResult":
            yield Static(self._header_text(), id="header")
            yield RichLog(id="log", wrap=True, markup=True, highlight=False, min_width=10)
            yield Static("", id="activity")
            with Horizontal(id="approval"):
                yield Static("⚠ aprovar a ação pendente?", id="approval-label")
                yield Button("Aprovar", id="approve", variant="success")
                yield Button("Sempre", id="always", variant="warning")     # libera a categoria a sessão toda
                yield Button("Negar", id="deny", variant="error")
            yield OptionList(id="cmdmenu")             # autocomplete navegável (↑↓ Enter) + clicável (mouse)
            from okami import commands as _cmds
            yield Input(placeholder="fala comigo…   / p/ comandos (↑↓ Enter ou clique) · ^C copia · ^D sai",
                        id="input", suggester=SuggestFromList(_cmds.all_slash_names("chat"), case_sensitive=False))
            yield Static("", id="status")

        def on_mount(self) -> None:
            try:                                           # tema da marca como default (/skin troca)
                self.register_theme(OKAMI_THEME)
                self.theme = "okami"
            except Exception:  # noqa: BLE001 — se a API de tema mudar, segue no tema padrão
                pass
            self.query_one("#approval").display = False
            if self._new:
                self.ep.session(self._cid).history.clear()
                self.ep.store.reset(self._cid)
            from rich.text import Text
            log = self.query_one("#log", RichLog)
            try:                                           # painel rico estilo Hermes (wordmark + hero + tools/skills)
                log.write(_tui.welcome(version=self._version, model=self._model_label,
                                       provider=self._provider_label, cwd=Path.cwd(),
                                       session=self._session_id, agent=self._agent,
                                       tools=self._tools, skills=self._skills,
                                       resumed=len(self.ep.session(self._cid).history) // 2))
                log.write(Text(""))
            except Exception:  # noqa: BLE001
                log.write(f"Okami · {self._agent} · {self._model_label}")
            self.query_one("#input", Input).focus()
            self.set_interval(0.12, self._tick)
            threading.Thread(target=self._worker, daemon=True).start()
            if self._on_started:
                self._on_started(self)

        def on_unmount(self) -> None:
            self._stop.set()

        # ---- sinks (sempre via call_from_thread quando vier de fundo) ---------
        def sink_message(self, chat_id, text: str) -> None:
            from rich.text import Text
            head = text[:1]
            # Só o INDICADOR de "pensando" (💭) some — a barra de status já mostra "🧠 pensando". NÃO casar
            # por 🧠 cru: comandos respondem com 🧠 (ex.: /model "🧠 modelo: …") e sumiam (bug do usuário).
            if head == "💭":
                return
            log = self.query_one("#log", RichLog)
            if head in _SYS_MARKS and head not in _REPLY_MARKS:   # nota de sistema (🧬 🎭 ↻ 🧹 ⏰ …)
                self.transcript.append(("note", text))
                log.write(Text("  " + text, style=_SYS_COLOR.get(head, "dim")))
                return
            body = text[1:].strip() if head in _REPLY_MARKS else text   # fala do agente
            self._tokbuf = ""                             # #16: zera o buffer de streaming no fim do turno
            self.transcript.append(("agent", text))       # (senão um token parcial sem \n vaza pro próximo)
            log.write(self._agent_block(body))

        def sink_event(self, e: dict) -> None:
            kind = e.get("kind")
            if kind == "token":                           # #16: streaming token-a-token → escreve por LINHA
                from rich.text import Text
                self._tokbuf = getattr(self, "_tokbuf", "") + e.get("text", "")
                while "\n" in self._tokbuf:
                    line, self._tokbuf = self._tokbuf.split("\n", 1)
                    self.query_one("#log", RichLog).write(Text(line, style="dim"))
                if len(self._tokbuf) > 8000:                  # linha gigante SEM \n: descarrega p/ não inchar
                    self.query_one("#log", RichLog).write(Text(self._tokbuf, style="dim"))
                    self._tokbuf = ""
                return
            if kind == "tool_start":                      # terminal VIVO: guarda a tool em execução p/ o _tick
                self._running = (e.get("tool", ""), e.get("args") or {}, time.monotonic())
                return                                    # (o card final, com resultado, vem no 'step')
            if kind == "step":                            # terminou → some o indicador vivo; o card vai pro log
                self._running = None
            block = _tui.tool_block(e, self._details)     # tool-card (edit→diff, write→código, etc.)
            if block is not None:
                self.query_one("#log", RichLog).write(block)

        def sink_note(self, text: str) -> None:
            from rich.text import Text
            self.transcript.append(("note", text))
            self.query_one("#log", RichLog).write(Text(text, style="dim"))

        def _event_from_thread(self, e: dict) -> None:
            self.call_from_thread(self.sink_event, e)

        # ---- input + autocomplete -------------------------------------------
        def _cmdmenu(self):
            try:                                          # pode não existir durante o teardown da app
                return self.query_one("#cmdmenu", OptionList)
            except Exception:  # noqa: BLE001
                return None

        def on_input_changed(self, event) -> None:
            # autocomplete: digitou '/' → popula o menu navegável; some ao apagar ou começar os args.
            menu = self._cmdmenu()
            if menu is None:
                return
            matches = _tui.command_matches(event.value)
            if not matches:
                menu.display = False
                return
            menu.clear_options()
            for label, name in matches:
                menu.add_option(Option(label, id=name))
            menu.display = True
            menu.highlighted = 0

        def _accept_cmd(self, name) -> None:
            """Completa o input com '/<comando> ' e fecha o menu (foca o input p/ digitar os args)."""
            menu = self._cmdmenu()
            if menu is not None:
                menu.display = False
            inp = self.query_one("#input", Input)
            inp.value = "/" + str(name) + " "
            inp.cursor_position = len(inp.value)
            inp.focus()

        def _accept_highlighted(self) -> bool:
            menu = self._cmdmenu()
            if menu is None or not menu.display or not menu.option_count or menu.highlighted is None:
                return False
            self._accept_cmd(menu.get_option_at_index(menu.highlighted).id)
            return True

        def on_key(self, event) -> None:
            # menu de comandos aberto: ↑↓ navegam o menu, Esc fecha. menu fechado: ↑↓ recuperam o histórico
            # das mensagens enviadas (paridade Hermes), desde que o foco esteja no input.
            menu = self._cmdmenu()
            if menu is not None and menu.display and menu.option_count:
                if event.key in ("down", "up"):
                    (menu.action_cursor_down if event.key == "down" else menu.action_cursor_up)()
                    event.stop()
                    event.prevent_default()
                elif event.key == "escape":
                    menu.display = False
                    event.stop()
                return
            if event.key in ("up", "down"):               # menu fechado → ↑/↓ = histórico do input
                try:
                    inp = self.query_one("#input", Input)
                except Exception:  # noqa: BLE001
                    return
                if not inp.has_focus:
                    return
                val = self._history.prev() if event.key == "up" else self._history.next()
                inp.value = val
                inp.cursor_position = len(val)
                event.stop()
                event.prevent_default()

        def on_option_list_option_selected(self, event) -> None:
            # clique do MOUSE (ou Enter dentro do menu) numa sugestão → completa.
            self._accept_cmd(event.option.id)
            event.stop()

        def on_input_submitted(self, event) -> None:
            if self._accept_highlighted():               # Enter com o menu aberto → completa, não envia
                return
            text = event.value
            event.input.value = ""
            menu = self._cmdmenu()                        # pode ser None no teardown → não derruba o submit
            if menu is not None:
                menu.display = False
            if not text.strip():
                return
            self._history.add(text)                       # ↑/↓ recall depois
            self.transcript.append(("user", text))
            self.query_one("#log", RichLog).write(self._user_block(text))
            self._input_q.put(text)

        def on_button_pressed(self, event) -> None:
            if event.button.id == "approve":
                self._input_q.put("/yes")
            elif event.button.id == "always":
                self._input_q.put("/always")
            elif event.button.id == "deny":
                self._input_q.put("/no")

        def show_approval(self, ask: str) -> None:
            """Abre o painel de aprovação com a AÇÃO (tool + arg + reason + risk) DESTACADAS.

            O ask vem do endpoint no formato `⚠ Aprovar [{tool}] · {brief}
{reason} (risco={risk})
/yes ...`.
            Renderizamos um painel COLORIDO: tool em ciano, brief em amarelo, reason em dim, risk badge
            pela cor (verde/amarelo/laranja/vermelho), comandos em mute. Resolve "aprovar rm -rf e tao
            facil quanto cat" -- a acao fica visualmente proeminente."""
            self._approval_text = ask or "⚠ aprovar a ação pendente?"
            try:
                panel = _format_approval_panel(self._approval_text)
                self.query_one("#approval-label", Static).update(panel)
                self.query_one("#approval").display = True
                self.query_one("#approve", Button).focus()
            except Exception:  # noqa: BLE001
                pass

        
        def _busy(self) -> bool:
            s = self.ep.sessions.get(self._cid)
            return bool(s and s.busy)

        def _worker(self) -> None:
            while not self._stop.is_set():
                try:
                    line = self._input_q.get(timeout=0.1)
                except queue.Empty:
                    line = None
                if line is not None:
                    d = _route_repl_line(line, busy=self._busy(),
                                         pending_approval=self._cid in self.ep._pending,
                                         pending_clarify=self._cid in getattr(self.ep, "_clarify_pending", {}))
                    if d == "exit":
                        self.call_from_thread(self.action_quit_app)
                        break
                    if d == "help":
                        self.call_from_thread(lambda: self.query_one("#log", RichLog).write(_tui.help_table()))
                    elif d == "details":
                        self.call_from_thread(self._cmd_details, line)
                    elif d == "agents":
                        self.call_from_thread(self._cmd_agents)
                    elif d == "skin":
                        self.call_from_thread(self._cmd_skin, line)
                    elif d == "mouse":
                        self.call_from_thread(self._cmd_mouse, line)
                    elif d == "replay":                  # M8: últimos tool-calls c/ args+saída (cliente)
                        self.call_from_thread(self._cmd_replay, line)
                    elif d == "copy":
                        self.call_from_thread(self._cmd_copy, line)
                    elif d in ("approval", "stop", "clarify"):   # clarify: responde a pergunta direto (turno bloqueado)
                        self._safe_handle(line)
                    else:                                  # handle | queue → fila (1 só produtor)
                        self.inflight.append(line)
                        if d == "queue":
                            n = len(self.inflight)
                            self.call_from_thread(self.sink_note, f"↩ na fila ({n}) — respondo assim que terminar")
                if self.inflight and not self._busy() and self._cid not in self.ep._pending:
                    self._safe_handle(self.inflight.popleft())

        def _safe_handle(self, line: str) -> None:
            try:
                self.ep.handle(self._cid, line)
            except Exception as e:  # noqa: BLE001 — um turno que falha não derruba a TUI
                self.call_from_thread(self.sink_note, f"erro: {e}")

        def _cmd_replay(self, line: str) -> None:
            """M8: mostra os últimos N tool-calls com args COMPLETOS + saída (mesma view do REPL). Era um
            buraco: na TUI o /replay caía como mensagem pro agente."""
            arg = line.split(maxsplit=1)[1].strip() if " " in line else ""
            try:
                n = max(1, min(int(arg), 60)) if arg else 10
            except ValueError:
                n = 10
            self.query_one("#log", RichLog).write(_tui.replay_view(list(getattr(self.ep, "_step_log", []) or []), n))

        def _cmd_copy(self, line: str) -> None:
            """Copia a ÚLTIMA resposta da agente pro clipboard (sem precisar selecionar). `/copy all` =
            conversa inteira. Resolve "não consigo selecionar no TUI" — é só digitar /copy e colar."""
            from rich.text import Text
            log = self.query_one("#log", RichLog)
            arg = line.split(maxsplit=1)[1].strip().lower() if " " in line else ""
            if arg in ("all", "tudo", "conversa", "chat"):
                text = "\n\n".join(f"{'você' if k == 'user' else 'okami'}: {t}"
                                   for k, t in self.transcript if k in ("user", "agent"))
                label = "conversa inteira"
            else:
                agents = [t for k, t in self.transcript if k == "agent"]
                text, label = (agents[-1] if agents else ""), "última resposta"
            if not text.strip():
                log.write(Text("  📋 nada pra copiar ainda.", style="dim"))
                return
            try:
                self.copy_to_clipboard(text)
                log.write(Text(f"  📋 copiado: {label} ({len(text)} chars) — cole onde quiser. "
                               "(/copy all = conversa inteira)", style="dim"))
            except Exception as e:  # noqa: BLE001
                log.write(Text(f"  📋 não consegui copiar: {e}", style="dim"))

        def _cmd_details(self, line: str) -> None:
            from rich.text import Text
            arg = line.split(maxsplit=1)[1].strip().lower() if " " in line else ""
            if arg in _tui._DETAIL_LEVELS:
                self._details = arg
            else:                                          # sem arg → cicla hidden→collapsed→expanded
                self._details = _tui._DETAIL_LEVELS[
                    (_tui._DETAIL_LEVELS.index(self._details) + 1) % len(_tui._DETAIL_LEVELS)]
            self.query_one("#log", RichLog).write(Text(f"  🔎 detalhes dos tool-calls: {self._details}", style="dim"))

        def _cmd_agents(self) -> None:
            s = self.ep.sessions.get(self._cid)
            self.query_one("#log", RichLog).write(
                _tui.activity_panel(bg=self.ep._bg, busy=self._busy(), queued=len(s.queued) if s else 0,
                                    procs=self.ep.process_brief()))

        def _cmd_skin(self, line: str) -> None:
            from rich.text import Text
            log = self.query_one("#log", RichLog)
            arg = line.split(maxsplit=1)[1].strip().lower() if " " in line else ""
            avail = ", ".join(_tui.SKINS)
            if not arg:
                log.write(Text(f"  🎨 tema atual: {self.theme}. Disponíveis: {avail}", style="dim"))
                return
            if arg in self.available_themes:
                self.theme = arg                           # reativo → re-tematiza a chrome na hora
                if _save_theme(arg):
                    log.write(Text(f"  🎨 tema → {arg} (salvo em {_PREFS_PATH()})", style="dim"))
                else:
                    log.write(Text(f"  🎨 tema → {arg} (não consegui persistir; vale só desta sessão)", style="dim"))
            else:
                log.write(Text(f"  🎨 tema '{arg}' não existe. Tente: {avail}", style="dim"))

        def _cmd_mouse(self, line: str) -> None:
            from rich.text import Text
            log = self.query_one("#log", RichLog)
            arg = line.split(maxsplit=1)[1].strip().lower() if " " in line else ""
            want = True if arg in ("on", "1", "yes") else False if arg in ("off", "0", "no") else not self._mouse_on
            drv = getattr(self, "_driver", None)
            fn = getattr(drv, "_enable_mouse_support" if want else "_disable_mouse_support", None)
            if fn is None:
                log.write(Text("  🖱 toggle de mouse não suportado nesta versão do Textual.", style="dim"))
                return
            try:
                fn()
                self._mouse_on = want
                log.write(Text(f"  🖱 mouse {'ON' if want else 'OFF (seleção nativa do terminal)'}", style="dim"))
            except Exception as e:  # noqa: BLE001 — driver pode recusar; não derruba a TUI
                log.write(Text(f"  🖱 não consegui mudar o mouse: {e}", style="dim"))

        # ---- timer: atividade + status + barra de aprovação ------------------
        def _tick(self) -> None:
            from rich.text import Text
            self._spin = (self._spin + 1) % len(_SPINNER)
            self._ticks += 1
            busy = self._busy()
            if not busy:
                self._running = None                       # turno acabou → garante que o indicador vivo some
            self._busy_since = (self._busy_since or time.monotonic()) if busy else None
            try:
                act = self.query_one("#activity", Static)
                if busy:
                    run = self._running
                    if run:                                # uma TOOL está rodando → mostra ela viva (Hermes):
                        tool, targs, t0 = run              # emoji + spinner + nome + arg + relógio
                        a = _tui.running_tool_text(tool, targs, spin=_SPINNER[self._spin],
                                                   elapsed=int(time.monotonic() - t0))
                    else:                                  # senão: "pensando" com verbo que ROTACIONA (FaceTicker)
                        el = int(time.monotonic() - (self._busy_since or time.monotonic()))
                        a = Text()
                        a.append(f"{_SPINNER[self._spin]} ", style="bold #ff7527")
                        a.append(f"{self._agent} está {_tui.thinking_phrase(self._ticks)}…", style="#ffb86c")
                        a.append(f"  {el}s", style="#3d3e50")
                    act.update(a)
                    act.display = True
                elif act.display:
                    act.display = False
                self.query_one("#status", Static).update(self._status_text())
            except Exception:  # noqa: BLE001
                pass                                   # erro no status NÃO pode esconder a aprovação ↓
            try:                                       # aprovação em try PRÓPRIO (desacoplado do status)
                pending = self._cid in self.ep._pending
                bar = self.query_one("#approval")
                if pending and not bar.display:        # abriu: garante visível + foco no Aprovar
                    bar.display = True
                    self.query_one("#approve", Button).focus()
                elif not pending and bar.display:      # resolveu: fecha + reseta o rótulo
                    bar.display = False
                    self.query_one("#approval-label", Static).update("⚠ aprovar a ação pendente?")
            except Exception:  # noqa: BLE001
                pass

        # ---- render helpers --------------------------------------------------
        def _header_text(self):
            from rich.text import Text
            t = Text(no_wrap=True, overflow="ellipsis")
            t.append(" 🐺 ", style="#ff7527")
            t.append("OKAMI", style="bold #ff7527")
            t.append("  ", style="")
            t.append(self._agent, style="#f4f4f8")
            t.append("  ·  ", style="#3d3e50")
            t.append(self._model_label, style="#b9bac8")
            t.append("  ·  ", style="#3d3e50")
            t.append(f"sessão {self._session_id}", style="#6c6d80")
            return t

        @staticmethod
        def _now() -> str:
            from datetime import datetime
            return datetime.now().strftime("%H:%M")

        def _author_line(self, name: str, color: str):
            # Régua de turno FORTE (barra ▌ + nome + hora que cruza a tela) — não só a corzinha do lado.
            return _tui.author_rule(name, color=color, when=self._now())

        def _agent_block(self, body: str):
            from rich.console import Group
            from rich.markdown import Markdown
            from rich.padding import Padding
            from rich.text import Text
            inner = Markdown(body) if body.strip() else Text("(sem resposta)", style="#6c6d80")
            return Group(Text(""), self._author_line(self._agent, "#ff7527"),
                         Padding(inner, (0, 0, 1, 2)))

        def _user_block(self, text: str):
            from rich.console import Group
            from rich.padding import Padding
            from rich.text import Text
            return Group(Text(""), self._author_line("você", "#00dfe8"),
                         Padding(Text(text, style="#f4f4f8"), (0, 0, 1, 2)))


        def _ctx_pct(self) -> int:
            try:                                          # ctx% REAL do último turno (tokens de entrada ÷ janela),
                return int(self.ep.store.entry(self._cid).get("ctx_pct", 0))   # gravado pelo endpoint
            except Exception:  # noqa: BLE001
                return 0

        def _turns(self) -> int:
            try:                                          # TOTAL de trocas (node_count÷2), não a janela capada em 8
                return int(self.ep.store.entry(self._cid).get("node_count", 0)) // 2
            except Exception:  # noqa: BLE001
                return len(self.ep.session(self._cid).history) // 2

        def _status_text(self):
            from rich.text import Text
            busy = self._busy()
            pending = self._cid in self.ep._pending
            turns = self._turns()
            pct = self._ctx_pct()
            gauge_n = max(0, min(10, round(10 * pct / 100)))
            gcolor = ("#00dfe8" if pct < 60 else "#ffb86c" if pct < 80 else
                      "#ff7527" if pct < 92 else "#ff5555")
            t = Text(no_wrap=True, overflow="ellipsis")          # nunca quebra linha (terminal estreito)
            if busy:
                t.append(f" {_SPINNER[self._spin]} ", style="bold #ff7527")
                t.append("🧠 pensando ", style="#ffb86c")
            elif pending:
                t.append(" ✍ ", style="bold #ff39d1")
                t.append("responda acima ", style="#ff39d1")
            else:
                t.append(" ● ", style="bold #00dfe8")
                t.append("pronto ", style="#6c6d80")
            t.append(f" {self._model_label} ", style="#b9bac8")
            t.append("· ctx ", style="#6c6d80")
            t.append("█" * gauge_n + "░" * (10 - gauge_n), style=gcolor)
            t.append(f" {pct}% ", style=gcolor)
            t.append(f"· {turns} trocas ", style="#6c6d80")
            if self.inflight:
                t.append(f"· {len(self.inflight)} na fila ", style="#ffb86c")
            t.append("· ^C parar · ^D sair", style="#3d3e50")
            return t

        # ---- ações -----------------------------------------------------------
        def action_ctrl_c(self) -> None:
            try:                                          # tem texto SELECIONADO (arraste o mouse) → COPIA
                sel = self.screen.get_selected_text() or ""
            except Exception:  # noqa: BLE001
                sel = ""
            if sel.strip():
                try:
                    self.copy_to_clipboard(sel)
                    self.clear_selection()
                except Exception:  # noqa: BLE001
                    pass
                self.sink_note(f"📋 copiado ({len(sel)} chars)")
                return
            inp = self.query_one("#input", Input)
            if self._busy():
                s = self.ep.sessions.get(self._cid)
                if s:
                    s.cancel = True
                self.sink_note("⏹ cancelando…")
            elif inp.value:
                inp.value = ""
            else:
                now = time.monotonic()
                if now - self._exit_armed < 1.2:
                    self.action_quit_app()
                else:
                    self._exit_armed = now
                    self.sink_note("Ctrl-C de novo (ou Ctrl-D) p/ sair")

        def action_ctrl_d(self) -> None:
            """Ctrl-D com double-tap de 1.2s p/ evitar saida acidental (vem do bash, onde ^D fecha).
            1o ^D -> "Ctrl-D de novo p/ sair" (toast) · 2o ^D em < 1.2s -> action_quit_app().
            """
            now = time.monotonic()
            if now - self._exit_armed < 1.2:
                self.action_quit_app()
            else:
                self._exit_armed = now
                self.sink_note("Ctrl-D de novo p/ sair (1.2s)")

        def action_quit_app(self) -> None:
            self._stop.set()
            self.exit()

        def action_clear_log(self) -> None:
            self.query_one("#log", RichLog).clear()

else:  # pragma: no cover - sem textual a classe nem existe
    OkamiChatApp = None  # type: ignore


def run_chat_tui(*, cfg, ws, name, cid, run_task, approval_mode="manual", model_label="",
                 provider_label="", ctx_budget=200_000, agent="okami", session_id="", tools=None,
                 skills=None, version="", new=False, spawn=None) -> bool:
    """Sobe a TUI de tela cheia. Devolve False se textual não estiver disponível (chamador cai no REPL)."""
    if not _HAS_TEXTUAL:
        return False
    app = OkamiChatApp(cfg=cfg, ws=ws, name=name, cid=cid, run_task=run_task,
                       approval_mode=approval_mode, model_label=model_label,
                       provider_label=provider_label, ctx_budget=ctx_budget, agent=agent,
                       session_id=session_id, tools=tools, skills=skills, version=version,
                       new=new, spawn=spawn)
    app.run()
    return True


def _format_approval_panel(ask: str):
    """Renderable Rich com a acao DESTACADA (tool/brief/reason/risk) para o painel #approval-label.
    Pura, testavel. Comandos /yes etc ficam em MUTE pra nao competir com a acao visualmente."""
    from rich.text import Text
    t = Text()
    raw = ask or "⚠ aprovar a ação pendente?"
    lines = raw.split(chr(10))
    if not lines:
        return Text(raw)
    head = lines[0]
    if "[" in head and "]" in head:
        i, j = head.find("["), head.find("]")
        t.append(head[:i], style="bold #ff7527")
        t.append(head[i:j + 1], style="bold #00dfe8")
        rest = head[j + 1:]
        if chr(0x00b7) in rest:
            k = rest.find(chr(0x00b7))
            t.append(rest[:k], style="#f4f4f8")
            t.append(rest[k:], style="bold #ffb86c")
        else:
            t.append(rest, style="#f4f4f8")
    else:
        t.append(head, style="bold #ff7527")
    risk_colors = {"low": "#2ecc71", "medium": "#ffb86c", "high": "#ff7527", "critical": "#ff5555"}
    for ln in lines[1:]:
        t.append(chr(10))
        low = ln.lower()
        if "risco=" in low:
            try:
                risk = low.split("risco=", 1)[1].split(")")[0].strip()
                rc = risk_colors.get(risk, "#b9bac8")
            except Exception:
                rc = "#b9bac8"
            i = ln.lower().find("(risco=")
            if i >= 0:
                t.append(ln[:i], style="dim")
                t.append(ln[i:ln.lower().find(")", i) + 1], style="bold " + rc)
                tail = ln[ln.lower().find(")", i) + 1:]
                if tail:
                    t.append(tail, style="dim")
            else:
                t.append(ln, style="dim")
        elif ln.strip().startswith("/"):
            t.append(ln, style="#6c6d80")
        else:
            t.append(ln, style="#b9bac8")
    return t


