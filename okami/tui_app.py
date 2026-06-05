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

    class OkamiChatApp(App):
        """App Textual do chat: header · log · aprovação · input · status."""

        CSS = """
        Screen { layout: vertical; background: #0d0d12; }
        #header { height: 1; padding: 0 1; background: #16161f; }
        #log { height: 1fr; padding: 1 2; background: #0d0d12; scrollbar-color: #ff7527; scrollbar-size: 1 1; }
        #activity { height: auto; display: none; padding: 0 2; }
        #approval { height: auto; display: none; padding: 1 2; background: #221a12; border-top: solid #ff7527; }
        #approval-label { width: 1fr; content-align: left middle; color: #ffb86c; }
        #input { border: round #3d3e50; background: #16161f; }
        #input:focus { border: round #ff7527; }
        #status { height: 1; padding: 0 1; color: #6c6d80; background: #16161f; }
        Button { min-width: 12; margin: 0 1; }
        Button#approve { background: #1f7a3d; }
        Button#deny { background: #7a2a2a; }
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
            yield Input(placeholder="fala comigo…   ↵ envia · /help · Ctrl-D sai", id="input")
            yield Static("", id="status")

        def on_mount(self) -> None:
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
            if head == "💭":                              # "está pensando…" → indicador animado, não polui o log
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
        def on_input_submitted(self, event) -> None:
            text = event.value
            event.input.value = ""
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
                _tui.activity_panel(bg=self.ep._bg, busy=self._busy(), queued=len(s.queued) if s else 0))

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
            from rich.text import Text
            t = Text()
            t.append("▌ ", style=color)
            t.append(name, style=f"bold {color}")
            t.append("  " + self._now(), style="#3d3e50")
            return t

        def _agent_block(self, body: str):
            from rich.console import Group
            from rich.markdown import Markdown
            from rich.padding import Padding
            from rich.text import Text
            inner = Markdown(body) if body.strip() else Text("(sem resposta)", style="#6c6d80")
            return Group(self._author_line(self._agent, "#ff7527"), Padding(inner, (0, 0, 1, 2)))

        def _user_block(self, text: str):
            from rich.console import Group
            from rich.padding import Padding
            from rich.text import Text
            return Group(self._author_line("você", "#00dfe8"),
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
                t.append("trabalhando ", style="#ffb86c")
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
