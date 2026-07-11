"""Request-local cancellation and watchdog state.

The context is deliberately independent of any provider transport.  It can stop the
caller promptly, while a transport without a physical abort handle remains bounded by
that transport's own finite timeout.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass


log = logging.getLogger(__name__)


class RequestCancelled(RuntimeError):
    """The request was cancelled and must not be retried or failed over."""


class RequestWatchdogTimeout(TimeoutError):
    """A request-local total, time-to-first-byte, or idle watchdog expired."""


@dataclass(frozen=True, slots=True)
class RequestTimeouts:
    total_s: float | None = None
    ttfb_s: float | None = None
    idle_s: float | None = None


class RequestContext:
    """State shared by one generation request and all of its retry/fallback work."""

    def __init__(
        self,
        limits: RequestTimeouts,
        *,
        clock: Callable[[], float] = time.monotonic,
        poll_s: float = 0.05,
        abort_grace_s: float = 0.25,
    ) -> None:
        self.request_id = uuid.uuid4().hex
        self.limits = limits
        self.clock = clock
        self.poll_s = max(0.001, float(poll_s))
        self.abort_grace_s = max(0.0, float(abort_grace_s))
        self.started_at = clock()
        self.first_event_at: float | None = None
        self.last_event_at: float | None = None

        self._cancelled = threading.Event()
        self._reason = ""
        self._aborters: list[Callable[[str], object]] = []
        self._registered_aborters: list[Callable[[str], object]] = []
        self._abort_lock = threading.Lock()
        self._aborted = False
        self._has_physical_abort = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def reason(self) -> str:
        with self._abort_lock:
            return self._reason

    @property
    def physical_abort_available(self) -> bool:
        """Whether a physical abort callback has been registered for this request."""
        with self._abort_lock:
            return self._has_physical_abort

    @property
    def abort_limitation(self) -> str | None:
        """Honest status when the context cannot physically kill underlying work."""
        if self.physical_abort_available:
            return None
        return ("no physical abort handle registered; underlying transport remains bounded "
                "only if it enforces its own finite timeout")

    def observe(self) -> None:
        now = self.clock()
        if self.first_event_at is None:
            self.first_event_at = now
        self.last_event_at = now

    def remaining(self) -> float | None:
        if self.limits.total_s is None:
            return None
        return max(0.0, self.limits.total_s - (self.clock() - self.started_at))

    def register_abort(self, callback: Callable[[str], object]) -> None:
        """Register a physical abort callback, or invoke it immediately if already cancelled.

        The callback is always invoked after releasing ``_abort_lock``.  A callback is
        registered by identity once, so repeated cancellation/registration cannot call
        the same abort handle twice.
        """
        if not callable(callback):
            raise TypeError("request abort callback must be callable")

        invoke_now = False
        reason = ""
        with self._abort_lock:
            if any(existing is callback for existing in self._registered_aborters):
                return
            self._registered_aborters.append(callback)
            self._has_physical_abort = True
            if self._aborted:
                invoke_now = True
                reason = self._reason
            else:
                self._aborters.append(callback)
        if invoke_now:
            self._invoke_aborters((callback,), reason)

    def cancel(self, reason: str = "user") -> bool:
        """Cancel once and invoke a snapshot of abort callbacks outside the lock."""
        reason = reason or "user"
        with self._abort_lock:
            if self._aborted:
                return False
            self._reason = reason
            self._cancelled.set()
            self._aborted = True
            aborters = tuple(self._aborters)
            self._aborters.clear()
        self._invoke_aborters(aborters, reason)
        return True

    def check(self) -> None:
        if self._cancelled.is_set():
            raise RequestCancelled(self.reason)

        now = self.clock()
        if self.limits.total_s is not None and now - self.started_at >= self.limits.total_s:
            self.cancel("total")
            raise RequestWatchdogTimeout("total")
        if (self.first_event_at is None and self.limits.ttfb_s is not None
                and now - self.started_at >= self.limits.ttfb_s):
            self.cancel("ttfb")
            raise RequestWatchdogTimeout("ttfb")
        if (self.last_event_at is not None and self.limits.idle_s is not None
                and now - self.last_event_at >= self.limits.idle_s):
            self.cancel("idle")
            raise RequestWatchdogTimeout("idle")

    def run(self, fn: Callable[[], object], *, cancel: Callable[[], bool] | None = None):
        """Run a legacy no-argument callable while polling request state.

        Python cannot preempt a running thread.  On cancellation/timeout this method
        invokes the registered abort handle(s), waits at most ``abort_grace_s``, and
        then raises.  If no physical handle exists, the worker remains bounded by the
        finite timeout enforced by its transport; this method never claims to kill it.
        """
        self.check()
        box: dict[str, object] = {}
        done = threading.Event()

        def worker() -> None:
            try:
                box["result"] = fn()
            except BaseException as exc:  # noqa: BLE001 — preserve the callable's exact failure
                box["error"] = exc
            finally:
                done.set()

        threading.Thread(target=worker, daemon=True).start()
        try:
            while not done.wait(self.poll_s):
                if cancel is not None and cancel():
                    self.cancel("user")
                self.check()
            if cancel is not None and cancel():
                self.cancel("user")
            self.check()
        except (RequestCancelled, RequestWatchdogTimeout):
            done.wait(self.abort_grace_s)
            raise

        error = box.get("error")
        if error is not None:
            raise error
        return box.get("result")

    @staticmethod
    def _invoke_aborters(aborters: tuple[Callable[[str], object], ...], reason: str) -> None:
        for abort in aborters:
            try:
                abort(reason)
            except Exception:  # noqa: BLE001 — one broken abort hook cannot block cancellation
                log.warning("request abort callback failed", exc_info=True)
