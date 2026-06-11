"""Streaming-by-edit (paridade OpenClaw draft-stream): em vez de inundar o chat com '💭 pensando' +
uma linha por tool, UMA mensagem de status é EDITADA ao vivo com o progresso recente. StreamEditor
coalesce as últimas N linhas e faz THROTTLE das edições (não spamma editMessage → evita 429)."""

from __future__ import annotations

from collections import deque


class StreamEditor:
    def __init__(self, *, min_interval: float = 1.2, keep: int = 6, header: str = ""):
        self.min_interval = min_interval     # mín. de segundos entre edições (anti-flood/429)
        self.header = header
        self._lines: deque[str] = deque(maxlen=keep)
        self._last_sent = -1e9

    def feed(self, line: str, now: float) -> None:
        line = (line or "").strip()
        if not line:
            return
        if self._lines and self._lines[-1] == line:        # idêntica seguida → não duplica
            return
        self._lines.append(line)

    def due(self, now: float) -> bool:
        """True se já passou o intervalo desde a última edição enviada (ou se nunca enviou)."""
        return (now - self._last_sent) >= self.min_interval

    def mark_sent(self, now: float) -> None:
        self._last_sent = now

    def render(self) -> str:
        body = "\n".join(self._lines)
        return f"{self.header}\n{body}" if self.header else body
