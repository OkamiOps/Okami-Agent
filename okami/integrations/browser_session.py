"""Sessão de browser PERSISTENTE (item 18-continuidade): mantém um Chromium (launch_persistent_context)
vivo entre chamadas de `browse()`, keyed por session_id (tipicamente `ctx.chat_id`/task id).

Por quê thread dedicada: a API sync do Playwright é thread-bound — todo objeto (context/page) só pode
ser usado na MESMA thread do processo que o criou. Uma VPS de longa duração recebe `browse()` de threads
diferentes a cada turno (pool de workers do gateway), então cada sessão roda sua PRÓPRIA thread com uma
fila de comandos: `call(fn)` empurra `fn` pra fila e bloqueia até o resultado voltar.

Idle-reaper: sem isto, cada sessão esquecida é um processo Chromium vivo pra sempre — uma VPS que roda
dias acumula dezenas de zumbis. Uma thread de fundo fecha sessão sem uso há mais de `idle_timeout`
segundos. Conceito portado de hermes-agent tools/browser_tool.py (cleanup por inatividade ~:1497,
sessão local ~:1973-2103) — implementação própria (fila+thread), não é cópia do código de lá.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SECONDS = 15 * 60      # 15min sem uso → fecha (evita Chromium zumbi na VPS)
_REAP_INTERVAL_SECONDS = 60
_CALL_TIMEOUT_SECONDS = 35
_STARTUP_TIMEOUT_SECONDS = 30


class SessionError(RuntimeError):
    """Sessão de browser não conseguiu iniciar/responder."""


@dataclass
class DialogEvent:
    """Último dialog (alert/confirm/prompt) visto na sessão — pra reportar ao modelo o que aconteceu."""
    type: str
    message: str
    handled_as: str          # "accept" | "dismiss"


class _SessionWorker:
    """Um Chromium + thread dedicada + fila de comandos p/ UMA sessão (session_id)."""

    def __init__(self, session_id: str, profile_dir: Path, dialog_policy: str = "dismiss"):
        self.session_id = session_id
        self.profile_dir = profile_dir
        self.last_used = time.time()
        self.refs: dict[int, dict] = {}         # mapa [N] -> elemento a11y DESTA sessão (não thread-local)
        self.current_url: str | None = None
        self.dialog_policy = dialog_policy        # "accept" | "dismiss" — o que fazer c/ confirm()/alert() sem pedido explícito
        self.last_dialog: DialogEvent | None = None
        self.context = None
        self.page = None
        self._cmds: "queue.Queue[tuple]" = queue.Queue()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._start_error: Exception | None = None
        self._thread = threading.Thread(target=self._run, name=f"browser-session-{session_id}", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=_STARTUP_TIMEOUT_SECONDS):
            raise SessionError(f"sessão de browser '{session_id}' não iniciou em {_STARTUP_TIMEOUT_SECONDS}s")
        if self._start_error:
            raise SessionError(f"sessão de browser '{session_id}' falhou ao iniciar: {self._start_error}")

    # -- thread da sessão -----------------------------------------------------------------------
    def _run(self) -> None:
        pw_cm = None
        try:
            from playwright.sync_api import sync_playwright
            pw_cm = sync_playwright()
            p = pw_cm.__enter__()
            self.context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir), headless=True)
            self.page = self.context.new_page()
            self.page.on("dialog", self._on_dialog)
        except Exception as e:  # noqa: BLE001
            self._start_error = e
            self._ready.set()
            return
        self._ready.set()
        while not self._closed.is_set():
            try:
                fn, args, kwargs, result_q = self._cmds.get(timeout=1)
            except queue.Empty:
                continue
            if fn is None:                        # sentinel de shutdown
                break
            try:
                result_q.put(("ok", fn(*args, **kwargs)))
            except Exception as e:  # noqa: BLE001
                result_q.put(("err", e))
        try:
            if self.context is not None:
                self.context.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if pw_cm is not None:
                pw_cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass

    def _on_dialog(self, dialog) -> None:
        """Dialog (alert/confirm/prompt) sem tratamento explícito NÃO PODE travar o turno — política
        default é dismiss (mais seguro; accept em confirm() de login pode disparar ação indesejada)."""
        try:
            self.last_dialog = DialogEvent(type=dialog.type, message=dialog.message,
                                           handled_as=self.dialog_policy)
            if self.dialog_policy == "accept":
                dialog.accept()
            else:
                dialog.dismiss()
        except Exception:  # noqa: BLE001 — dialog já pode ter sido resolvido; nunca derruba a sessão
            pass

    # -- API pública (chamada de QUALQUER thread) ------------------------------------------------
    def call(self, fn: Callable[..., Any], *args, timeout: float = _CALL_TIMEOUT_SECONDS, **kwargs) -> Any:
        """Roda `fn(self, *args, **kwargs)` NA thread da sessão; bloqueia até o resultado."""
        if self._closed.is_set():
            raise SessionError(f"sessão de browser '{self.session_id}' já foi fechada")
        self.last_used = time.time()
        result_q: "queue.Queue[tuple]" = queue.Queue()
        self._cmds.put((fn, (self, *args), kwargs, result_q))
        try:
            status, val = result_q.get(timeout=timeout)
        except queue.Empty as e:
            raise TimeoutError(f"sessão de browser '{self.session_id}' não respondeu em {timeout}s") from e
        if status == "err":
            raise val
        return val

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._cmds.put((None, (), {}, queue.Queue()))
        self._thread.join(timeout=10)


class BrowserSessionManager:
    """Registro de sessões vivas + reaper de inatividade. Uma instância default (`SESSIONS`) serve o
    processo inteiro; testes podem instanciar a própria pra isolamento."""

    def __init__(self, idle_timeout: float = IDLE_TIMEOUT_SECONDS):
        self.idle_timeout = idle_timeout
        self._sessions: dict[str, _SessionWorker] = {}
        self._lock = threading.Lock()
        self._reaper_started = False
        self._reaper_stop = threading.Event()

    def get_or_create(self, session_id: str, profile_dir: Path, dialog_policy: str = "dismiss") -> _SessionWorker:
        self._ensure_reaper()
        with self._lock:
            w = self._sessions.get(session_id)
            if w is not None:
                return w
        w = _SessionWorker(session_id, profile_dir, dialog_policy=dialog_policy)   # fora do lock: I/O
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:              # corrida: outra thread já criou — usa a dela, fecha a nossa
                w.close()
                return existing
            self._sessions[session_id] = w
            return w

    def get(self, session_id: str) -> _SessionWorker | None:
        with self._lock:
            return self._sessions.get(session_id)

    def close(self, session_id: str) -> bool:
        with self._lock:
            w = self._sessions.pop(session_id, None)
        if w is None:
            return False
        w.close()
        return True

    def close_all(self) -> None:
        with self._lock:
            items = list(self._sessions.items())
            self._sessions.clear()
        for _, w in items:
            w.close()

    def active_ids(self) -> list[str]:
        with self._lock:
            return list(self._sessions)

    def reap_once(self, now: float | None = None) -> list[str]:
        """Fecha (e devolve os ids de) sessões sem uso há mais de `idle_timeout`s. Síncrono — chamado
        pelo loop de fundo, mas testável diretamente sem esperar tempo real."""
        now = now if now is not None else time.time()
        stale: list[str] = []
        with self._lock:
            for sid, w in list(self._sessions.items()):
                if now - w.last_used > self.idle_timeout:
                    stale.append(sid)
                    del self._sessions[sid]
        for sid in stale:
            logger.info("browser session idle reap: %s", sid)
        return stale

    def _ensure_reaper(self) -> None:
        if self._reaper_started:
            return
        self._reaper_started = True
        t = threading.Thread(target=self._reap_loop, name="browser-session-reaper", daemon=True)
        t.start()

    def _reap_loop(self) -> None:
        while not self._reaper_stop.wait(_REAP_INTERVAL_SECONDS):
            try:
                self.reap_once()
            except Exception:  # noqa: BLE001 — reaper nunca pode morrer por 1 sessão zoada
                logger.exception("erro no reaper de sessões de browser")


# Registro default do processo — a Browse tool usa este singleton (testes preferem instância própria).
SESSIONS = BrowserSessionManager()
