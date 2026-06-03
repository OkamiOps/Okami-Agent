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

    # --- saída -----------------------------------------------------------------
    def _print(self, text: str) -> None:
        if self._console is not None:
            self._console.print(self._render(text))
        else:  # pragma: no cover - fallback sem rich
            print(text)

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
