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
    # Notificações de sistema de 1 linha (não renderizar como markdown). "·" = rodapé de custo (dim).
    _SYS_MARKS = {"💭", "🧠", "🧬", "🎨", "🎭", "⏰", "↻", "🧹", "⏹", "⚡", "🔒", "🚫", "🔊", "▶", "·"}

    # --- saída -----------------------------------------------------------------
    def _print(self, text: str) -> None:
        if self._console is None:  # pragma: no cover - fallback sem rich
            print(text)
            return
        head = text[:1]
        is_reply = head in self._REPLY_MARKS or head not in self._SYS_MARKS   # fala do agente, não sistema
        if not is_reply:                                                      # nota de sistema / rodapé → 1 linha
            self._console.print(self._render(text))
            return
        body = text[1:].strip() if head in self._REPLY_MARKS else text
        self._console.print(self._reply_panel(body, head))                   # resposta em MOLDURA (estilo Hermes)

    def _reply_panel(self, body: str, head: str):
        """Resposta do agente numa MOLDURA arredondada (título = 🐺 agente · hora; borda laranja da marca),
        com o corpo em Markdown. É o 'response box' do Hermes — frame claro, não só uma régua."""
        from datetime import datetime
        from rich.box import ROUNDED
        from rich.markdown import Markdown
        from rich.panel import Panel
        from rich.text import Text
        inner = Markdown(body) if ("```" in body or "\n" in body.strip()) else Text(body)
        # cor da borda pelo prefixo de estado (sucesso/aviso/erro) — default laranja da marca
        bc = {"✅": "#2ecc71", "⚠": "#ffb86c", "❌": "#ff5555", "❓": "#00dfe8"}.get(head, "#ff7527")
        return Panel(inner, title=f"[bold {bc}]🐺 {self.agent_id}[/]", title_align="left",
                     subtitle=f"[dim]{datetime.now().strftime('%H:%M')}[/]", subtitle_align="right",
                     border_style=bc, box=ROUNDED, padding=(0, 1), expand=True)

    @staticmethod
    def _render(text: str) -> str:
        """Colore os prefixos de status do AgentEndpoint p/ ficar legível no terminal."""
        marks = {"✅": "green", "⚠": "yellow", "❌": "red", "❓": "cyan", "▶": "dim", "·": "dim",
                 "🧬": "magenta", "🎨": "magenta", "🎭": "magenta", "⏰": "blue", "↻": "blue",
                 "🧹": "dim", "⏹": "yellow", "⚡": "yellow", "🔒": "dim", "🚫": "red"}
        head = text[:1]
        color = marks.get(head)
        # Rich: escapa nada (texto do agente é confiável); só pinta a linha toda se tiver prefixo.
        return f"[{color}]{text}[/{color}]" if color else text

    def send(self, chat_id, text: str) -> None:
        self.sent.append((str(chat_id), text))
        self._print(text)

    def send_approval(self, chat_id, text: str, nonce: str = "") -> None:
        """APROVAÇÃO no REPL: toca o SINO (bell) + caixa BERRANTE — pra você NÃO perder o run sem ver.
        O `text` já traz a ação + as opções (/yes · /always · /no)."""
        self.sent.append((str(chat_id), text))
        if self._console is None:  # pragma: no cover
            print("\a⚠ APROVAÇÃO PENDENTE — /yes /always /no\n" + text)
            return
        import sys
        try:
            sys.stdout.write("\a")               # BELL: alerta sonoro do terminal (mata o "não percebi")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass
        from rich.box import HEAVY
        from rich.console import Group
        from rich.panel import Panel
        from rich.text import Text
        body = Group(Text(text, style="bold"),
                     Text("→ tecle  y (sim)  ·  a (sempre, não pergunta mais)  ·  n (não)",
                          style="bold green"))
        self._console.print(Panel(body, title="[bold black on yellow] ⚠ APROVAÇÃO PENDENTE [/]",
                                  title_align="left", border_style="bold yellow", box=HEAVY, padding=(0, 1)))

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
