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
    from textual.widgets import Button, Input, RichLog, Static
    _HAS_TEXTUAL = True
except Exception:  # noqa: BLE001 — sem textual: o chamador cai no REPL
    _HAS_TEXTUAL = False

# Prefixos que ENVOLVEM uma resposta do agente vs. notificações de sistema de 1 linha (espelha o
# TerminalChannel pra renderização consistente entre REPL e TUI).
_REPLY_MARKS = {"✅", "⚠", "❌", "❓"}
_SYS_MARKS = {"💭", "🧬", "🎨", "🎭", "⏰", "↻", "🧹", "⏹", "⚡", "🔒", "🚫", "🔊", "▶"}
_SYS_COLOR = {"💭": "dim", "🧬": "magenta", "🎨": "magenta", "🎭": "magenta", "⏰": "blue",
              "↻": "blue", "🧹": "dim", "⏹": "yellow", "⚡": "yellow", "🔒": "dim", "🚫": "red",
              "🔊": "cyan", "▶": "dim", "✅": "green", "⚠": "yellow", "❌": "red", "❓": "cyan"}
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

    class OkamiChatApp(App):
        """App Textual do chat: header · log · aprovação · input · status."""

        CSS = """
        Screen { layout: vertical; background: $surface; }
        #header { height: auto; padding: 0 1; color: $text; }
        #log { height: 1fr; padding: 0 1; border: round #3d3e50; scrollbar-color: #ff7527; }
        #approval { height: auto; display: none; padding: 0 1; background: #2a2118; }
        #approval-label { width: 1fr; content-align: left middle; color: #ffb86c; }
        #input { border: round #ff7527; }
        #input:focus { border: round #ff39d1; }
        #status { height: 1; padding: 0 1; color: $text-muted; background: $panel; }
        Button { min-width: 10; margin: 0 1; }
        """

        BINDINGS = [
            Binding("ctrl+d", "quit_app", "sair", priority=True),
            Binding("ctrl+c", "ctrl_c", "cancelar/sair", priority=True, show=False),
            Binding("ctrl+l", "clear_log", "limpar"),
        ]

        def __init__(self, *, cfg, ws, name, cid, run_task, approval_mode="manual",
                     model_label="", ctx_budget=200_000, agent="okami", session_id="",
                     tools=None, skills=None, version="", new=False, spawn=None, on_started=None):
            super().__init__()
            from okami.gateway import AgentEndpoint
            self._cid = cid
            self._model_label = model_label
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
                                    spawn=spawn)
            self.inflight: deque[str] = deque()
            self._input_q: queue.Queue[str] = queue.Queue()
            self._stop = threading.Event()
            self._spin = 0
            self._exit_armed = 0.0
            self.transcript: list[tuple[str, str]] = []   # (kind, text) p/ teste

        # ---- layout ----------------------------------------------------------
        def compose(self) -> "ComposeResult":
            yield Static(self._header_text(), id="header")
            yield RichLog(id="log", wrap=True, markup=True, highlight=False, min_width=10)
            with Horizontal(id="approval"):
                yield Static("⚠ aprovar a ação pendente?", id="approval-label")
                yield Button("Aprovar", id="approve", variant="success")
                yield Button("Negar", id="deny", variant="error")
            yield Input(placeholder="fala comigo…   /help · Ctrl-D sai", id="input")
            yield Static("", id="status")

        def on_mount(self) -> None:
            self.query_one("#approval").display = False
            if self._new:
                self.ep.session(self._cid).history.clear()
                self.ep.store.reset(self._cid)
            log = self.query_one("#log", RichLog)
            try:                                           # banner de boas-vindas (reusa o tui.welcome)
                log.write(_tui.welcome(version=self._version, model=self._model_label, provider="",
                                       cwd=Path.cwd(), session=self._session_id,
                                       agent=self._agent, tools=self._tools, skills=self._skills,
                                       resumed=len(self.ep.session(self._cid).history) // 2))
            except Exception:  # noqa: BLE001
                log.write(f"Okami · {self._agent} · {self._model_label}")
            self.query_one("#input", Input).focus()
            self.set_interval(0.25, self._tick)
            threading.Thread(target=self._worker, daemon=True).start()
            if self._on_started:
                self._on_started(self)

        def on_unmount(self) -> None:
            self._stop.set()

        # ---- sinks (sempre via call_from_thread quando vier de fundo) ---------
        def sink_message(self, chat_id, text: str) -> None:
            self.transcript.append(("agent", text))
            self.query_one("#log", RichLog).write(_render_message(text))

        def sink_event(self, e: dict) -> None:
            line = _tui.event_line(e)
            if line is not None:
                self.query_one("#log", RichLog).write(line)

        def sink_note(self, text: str) -> None:
            from rich.text import Text
            self.transcript.append(("note", text))
            self.query_one("#log", RichLog).write(Text(text, style="dim"))

        def _event_from_thread(self, e: dict) -> None:
            self.call_from_thread(self.sink_event, e)

        # ---- input -----------------------------------------------------------
        def on_input_submitted(self, event) -> None:
            text = event.value
            event.input.value = ""
            if not text.strip():
                return
            from rich.text import Text
            self.transcript.append(("user", text))
            self.query_one("#log", RichLog).write(Text("› " + text, style="bold #ff7527"))
            self._input_q.put(text)

        def on_button_pressed(self, event) -> None:
            if event.button.id == "approve":
                self._input_q.put("/yes")
            elif event.button.id == "deny":
                self._input_q.put("/no")

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

        # ---- timer: status + barra de aprovação ------------------------------
        def _tick(self) -> None:
            self._spin = (self._spin + 1) % len(_SPINNER)
            try:
                self.query_one("#status", Static).update(self._status_text())
            except Exception:  # noqa: BLE001
                return
            pending = self._cid in self.ep._pending
            bar = self.query_one("#approval")
            if pending != bool(bar.display):
                bar.display = pending
                if pending:
                    self.query_one("#approve", Button).focus()

        # ---- render helpers --------------------------------------------------
        def _header_text(self):
            from rich.text import Text
            t = Text()
            t.append(" 🐺 Okami ", style="bold #ff7527")
            t.append(f"· {self._agent} ", style="#f4f4f8")
            t.append(f"· {self._model_label} ", style="#b9bac8")
            t.append(f"· sessão {self._session_id}", style="#6c6d80")
            return t

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
            t = Text()
            if busy:
                t.append(f" {_SPINNER[self._spin]} ", style="bold #ff7527")
                t.append("trabalhando ", style="#ffb86c")
            elif pending:
                t.append(" ✍ ", style="bold #ff39d1")
                t.append("responda a aprovação ", style="#ff39d1")
            else:
                t.append(" ● ", style="bold #00dfe8")
                t.append("pronto ", style="#6c6d80")
            t.append(f" {self._model_label} ", style="#b9bac8")
            t.append("· ctx ", style="#6c6d80")
            t.append("█" * gauge_n + "░" * (10 - gauge_n), style=gcolor)
            t.append(f" {pct:>3}% ", style=gcolor)
            t.append(f"· {turns} trocas ", style="#6c6d80")
            if self.inflight:
                t.append(f"· {len(self.inflight)} na fila ", style="#ffb86c")
            t.append("· Ctrl-C cancela · Ctrl-D sai", style="#3d3e50")
            return t

        # ---- ações -----------------------------------------------------------
        def action_ctrl_c(self) -> None:
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
                 ctx_budget=200_000, agent="okami", session_id="", tools=None, skills=None,
                 version="", new=False, spawn=None) -> bool:
    """Sobe a TUI de tela cheia. Devolve False se textual não estiver disponível (chamador cai no REPL)."""
    if not _HAS_TEXTUAL:
        return False
    app = OkamiChatApp(cfg=cfg, ws=ws, name=name, cid=cid, run_task=run_task,
                       approval_mode=approval_mode, model_label=model_label, ctx_budget=ctx_budget,
                       agent=agent, session_id=session_id, tools=tools, skills=skills,
                       version=version, new=new, spawn=spawn)
    app.run()
    return True
