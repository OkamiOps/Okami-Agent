"""Streaming-by-edit (paridade OpenClaw draft-stream): em vez de inundar o chat com '💭 pensando' +
uma linha por tool, UMA mensagem de status é EDITADA ao vivo com o progresso recente. StreamEditor
coalesce as últimas N linhas e faz THROTTLE das edições (não spamma editMessage → evita 429)."""

from __future__ import annotations

from collections import deque


class StreamEditor:
    def __init__(self, *, min_interval: float = 1.2, keep: int = 6, header: str = "", adaptive: bool = True):
        self.min_interval = min_interval     # TETO de segundos entre edições (anti-flood/429)
        self.adaptive = adaptive             # conteúdo curto edita mais rápido (UX); longo usa o teto cheio
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

    def _interval(self, size: int | None = None) -> float:
        """Intervalo efetivo até a PRÓXIMA edição (batch-delay adaptativo, paridade Hermes). Curto edita mais
        rápido (resposta snappy), longo throttle cheio (eficiência/anti-429). Nunca passa do teto min_interval.
        `size`: tamanho do conteúdo a editar — o caminho de STREAMING token-a-token tem o texto FORA do
        deque (_lines), então PRECISA passar len(buffer) aqui, senão o intervalo trava no piso curto."""
        if not self.adaptive:
            return self.min_interval
        n = size if size is not None else len(self.render())
        if n <= 320:
            return min(0.5, self.min_interval)       # resposta curta → atualiza ~2x mais rápido
        if n <= 1024:
            return min(0.8, self.min_interval)
        return self.min_interval                     # longo → teto cheio (poucas edições, anti-429)

    def due(self, now: float, size: int | None = None) -> bool:
        """True se já passou o intervalo (adaptativo) desde a última edição enviada (ou se nunca enviou).
        Passe `size` no caminho de streaming token-a-token (texto fora do deque)."""
        return (now - self._last_sent) >= self._interval(size)

    def mark_sent(self, now: float) -> None:
        self._last_sent = now

    def render(self) -> str:
        body = "\n".join(self._lines)
        return f"{self.header}\n{body}" if self.header else body
