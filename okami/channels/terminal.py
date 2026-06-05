"""Canal de TERMINAL (§13) — falar com o agente no console, sem Telegram.

É um `Channel` como qualquer outro: o gateway/`AgentEndpoint` não sabe que é terminal — só chama
`send()` (que imprime) e recebe mensagens por `handle()` (o REPL injeta direto, sem `poll()`).
Assim o chat de terminal herda DE GRAÇA: sessão persistente, slash commands, persona evolutiva,
aprovação go/no-go, vision — tudo o que o Telegram tem. (Estilo Hermes `hermes chat`.)
"""

from __future__ import annotations

from okami.channels.base import Channel


class TerminalChannel(Channel):
    """Canal síncrono de console. `send()` imprime; o REPL chama `AgentEndpoint.handle()` direto."""

    name = "terminal"

    def __init__(self, agent_id: str = "okami", *, console=None, allow_chats=None):
        self.agent_id = agent_id
        self._console = console
        self.sent: list[tuple[str, str]] = []   # histórico de saídas (útil em teste)
        self.allow_chats = allow_chats

    # Prefixos que ENVOLVEM uma resposta do agente (corpo pode ter markdown/código).
    _REPLY_MARKS = {"✅", "⚠", "❌", "❓"}
    # Notificações de sistema de 1 linha (não renderizar como markdown).
    _SYS_MARKS = {"💭", "🧠", "🧬", "🎨", "🎭", "⏰", "↻", "🧹", "⏹", "⚡", "🔒", "🚫", "🔊", "▶"}

    # --- saída -----------------------------------------------------------------
    def _print(self, text: str) -> None:
        if self._console is None:  # pragma: no cover - fallback sem rich
            print(text)
            return
        head = text[:1]
        is_reply = head in self._REPLY_MARKS or head not in self._SYS_MARKS   # fala do agente, não sistema
        body = text[1:].strip() if head in self._REPLY_MARKS else text
        if is_reply:
            try:
                self._console.print(self._turn_rule())                        # separa o turno do agente
            except Exception:  # noqa: BLE001 — a régua é cosmética; nunca impede a resposta
                pass
        if is_reply and ("```" in body or "\n" in body.strip()):             # código/lista → Markdown
            from rich.markdown import Markdown
            self._console.print(Markdown(body))
        else:
            self._console.print(self._render(text))

    def _turn_rule(self):
        """Régua de turno do agente (▌ okami · hora) — separação clara no REPL, igual à TUI."""
        from datetime import datetime
        from okami import tui as _tui
        return _tui.author_rule(self.agent_id, color="#ff7527",
                                when=datetime.now().strftime("%H:%M"))

    @staticmethod
    def _render(text: str) -> str:
        """Colore os prefixos de status do AgentEndpoint p/ ficar legível no terminal."""
        marks = {"✅": "green", "⚠": "yellow", "❌": "red", "❓": "cyan", "▶": "dim",
                 "🧬": "magenta", "🎨": "magenta", "🎭": "magenta", "⏰": "blue", "↻": "blue",
                 "🧹": "dim", "⏹": "yellow", "⚡": "yellow", "🔒": "dim", "🚫": "red"}
        head = text[:1]
        color = marks.get(head)
        # Rich: escapa nada (texto do agente é confiável); só pinta a linha toda se tiver prefixo.
        return f"[{color}]{text}[/{color}]" if color else text

    def send(self, chat_id, text: str) -> None:
        self.sent.append((str(chat_id), text))
        self._print(text)

    def send_audio(self, chat_id, audio_path) -> None:
        self._print(f"[dim]🔊 áudio: {audio_path}[/dim]")

    # --- entrada ---------------------------------------------------------------
    def poll(self):
        """O REPL dirige via `handle()` diretamente; não há polling de rede."""
        return []

    def allowed(self, chat_id) -> bool:
        if self.allow_chats is None:
            return True
        return str(chat_id) in {str(c) for c in self.allow_chats}
