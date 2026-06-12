"""Circuit breaker POR PLATAFORMA (pesquisa #6 item 23, porta do _failed_platforms do Hermes).

Um canal que falha no poll repetidamente entra em backoff EXPONENCIAL (base→…→cap) — para de
martelar uma plataforma morta (token revogado, API fora) e poluir log/rede. `/platform list|pause|
resume` dá controle manual. In-memory por gateway (estado de runtime, não persiste).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class _State:
    fails: int = 0
    until: float = 0.0          # backoff: não pollar antes disto
    manual: bool = False        # pausa manual (não expira sozinha)


@dataclass
class PlatformBreaker:
    base: float = 30.0
    cap: float = 300.0
    _by: dict = field(default_factory=dict)

    def _s(self, name: str) -> _State:
        return self._by.setdefault(name, _State())

    def record_failure(self, name: str, *, now: float | None = None) -> float:
        """Conta uma falha de poll e agenda o próximo poll (backoff exponencial). Retorna o backoff (s)."""
        now = time.time() if now is None else now
        s = self._s(name)
        s.fails += 1
        backoff = min(self.cap, self.base * (2 ** (s.fails - 1)))
        s.until = now + backoff
        return backoff

    def record_success(self, name: str) -> None:
        """Poll deu certo → zera o contador e o backoff (recuperou)."""
        s = self._s(name)
        s.fails, s.until = 0, 0.0

    def should_poll(self, name: str, *, now: float | None = None) -> bool:
        """Pode pollar este canal agora? False se em backoff ou pausa manual."""
        now = time.time() if now is None else now
        s = self._by.get(name)
        if s is None:
            return True
        return not s.manual and s.until <= now

    def pause(self, name: str) -> None:
        self._s(name).manual = True

    def resume(self, name: str) -> None:
        s = self._s(name)
        s.manual, s.fails, s.until = False, 0, 0.0

    def status(self, *, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        out = []
        for name, s in sorted(self._by.items()):
            if s.manual:
                state = "paused"
            elif s.until > now:
                state = "backoff"
            else:
                state = "ok"
            out.append({"name": name, "state": state, "fails": s.fails,
                        "retry_in": max(0, int(s.until - now)) if state == "backoff" else 0})
        return out
