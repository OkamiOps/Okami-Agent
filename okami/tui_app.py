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

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal
    from textual.suggester import SuggestFromList
    from textual.widgets import Button, Input, RichLog, Static
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
        #cmdhints { height: auto; max-height: 11; display: none; padding: 0 1; background: $panel;
                    border-top: solid $accent; color: $text; }
        #approval { height: auto; display: none; padding: 1 2; background: $panel; border-top: solid $primary; }
        #approval-label { width: 1fr; content-align: left middle; color: $warning; }
        #input { border: round $panel; background: $surface; }
        #input:focus { border: round $accent; }
        #status { height: 1; padding: 0 1; color: $text-muted; background: $surface; }
        Button { min-width: 12; margin: 0 1; }
        Button#approve { background: $success; }
        Button#deny { background: $error; }
        """

        BINDINGS = [
            Binding("ctrl+d", "quit_app", "sair", priority=True),
            Binding("ctrl+c", "ctrl_c", "cancelar/sair", priority=True, show=False),
            Binding("ctrl+l", "clear_log", "limpar"),
        ]

        def __init__(self, *, cfg, ws, name, cid, run_task, approval_mode="manual",
                     model_label="", provider_label="", ctx_budget=200_000, agent="okami",
                     session_id="", tools=None, skills=None, version="", new=False, spawn=None,
                     on_started=None):
            super().__init__()
            from okami.gateway import AgentEndpoint
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
            self._mouse_on = True                         # /mouse off → solta o mouse p/ seleção nativa
            self.transcript: list[tuple[str, str]] = []   # (kind, text) p/ teste

        # ---- layout ----------------------------------------------------------
        def compose(self) -> "ComposeResult":
            yield Static(self._header_text(), id="header")
            yield RichLog(id="log", wrap=True, markup=True, highlight=False, min_width=10)
            yield Static("", id="activity")
            with Horizontal(id="approval"):
                yield Static("⚠ aprovar a ação pendente?", id="approval-label")
                yield Button("Aprovar", id="approve", variant="success")
                yield Button("Negar", id="deny", variant="error")
            yield Static("", id="cmdhints")           # autocomplete: aparece ao digitar '/'
            from okami import commands as _cmds
            yield Input(placeholder="fala comigo…   ↵ envia · / p/ comandos · → completa · ^C copia · ^D sai",
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
            self.transcript.append(("agent", text))
            log.write(self._agent_block(body))

        def sink_event(self, e: dict) -> None:
            line = _tui.event_line(e, self._details)
            if line is not None:
                self.query_one("#log", RichLog).write(line)

        def sink_note(self, text: str) -> None:
            from rich.text import Text
            self.transcript.append(("note", text))
            self.query_one("#log", RichLog).write(Text(text, style="dim"))

        def _event_from_thread(self, e: dict) -> None:
            self.call_from_thread(self.sink_event, e)

        # ---- input -----------------------------------------------------------
        def on_input_changed(self, event) -> None:
            # autocomplete: digitou '/' → mostra os comandos que casam (some ao apagar ou começar a digitar args)
            hints = _tui.command_hints(event.value)
            panel = self.query_one("#cmdhints", Static)
            if hints is None:
                panel.display = False
            else:
                panel.update(hints)
                panel.display = True

        def on_input_submitted(self, event) -> None:
            text = event.value
            event.input.value = ""
            try:
                self.query_one("#cmdhints", Static).display = False   # esconde o popup ao enviar
            except Exception:  # noqa: BLE001
                pass
            if not text.strip():
                return
            self.transcript.append(("user", text))
            self.query_one("#log", RichLog).write(self._user_block(text))
            self._input_q.put(text)

        def on_button_pressed(self, event) -> None:
            if event.button.id == "approve":
                self._input_q.put("/yes")
            elif event.button.id == "deny":
                self._input_q.put("/no")

        def show_approval(self, ask: str) -> None:
            """Abre o painel de aprovação com a AÇÃO (tool + arg) — chamado pelo send_approval do canal."""
            self._approval_text = ask or "⚠ aprovar a ação pendente?"
            try:
                self.query_one("#approval-label", Static).update(self._approval_text)
                self.query_one("#approval").display = True
                self.query_one("#approve", Button).focus()
            except Exception:  # noqa: BLE001
                pass

        # ---- worker (único produtor de turnos → sem corrida) -----------------
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
                                         pending_approval=self._cid in self.ep._pending)
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
                    elif d in ("approval", "stop"):
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
                log.write(Text(f"  🎨 tema → {arg}", style="dim"))
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
            busy = self._busy()
            self._busy_since = (self._busy_since or time.monotonic()) if busy else None
            try:
                act = self.query_one("#activity", Static)
                if busy:                                   # indicador VIVO de "raciocinando", com relógio
                    el = int(time.monotonic() - (self._busy_since or time.monotonic()))
                    a = Text()
                    a.append(f"{_SPINNER[self._spin]} ", style="bold #ff7527")
                    a.append(f"{self._agent} está raciocinando…", style="#ffb86c")
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
            used = sum(len(x) for _, x in self.ep.session(self._cid).history)
            return min(100, round(100 * used / self._ctx_budget))

        def _status_text(self):
            from rich.text import Text
            busy = self._busy()
            pending = self._cid in self.ep._pending
            turns = len(self.ep.session(self._cid).history) // 2
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
