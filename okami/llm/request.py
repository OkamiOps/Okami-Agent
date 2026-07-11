"""Request-local cancellation and watchdog state.

The context is deliberately independent of any provider transport.  It can stop the
caller promptly, while a transport without a physical abort handle remains bounded by
that transport's own finite timeout.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass


log = logging.getLogger(__name__)


def _positive_finite(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite and strictly positive")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be finite and strictly positive") from None
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and strictly positive")
    return number


@dataclass(frozen=True, slots=True)
class RequestTimeouts:
    total_s: float | None = None
    ttfb_s: float | None = None
    idle_s: float | None = None

    def __post_init__(self) -> None:
        for field in ("total_s", "ttfb_s", "idle_s"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _positive_finite(value, field))


class RequestCancelled(RuntimeError):
    """The request was cancelled and must not be retried or failed over."""

    def __init__(self, reason: str = "user") -> None:
        self.reason = reason or "user"
        super().__init__(self.reason)


class RequestWatchdogTimeout(TimeoutError):
    """A request-local total, time-to-first-byte, or idle watchdog expired."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class RequestContext:
    """State shared by one generation request and all of its retry/fallback work.

    ``_state_lock`` is the linearization point for cancellation, watchdog expiry,
    worker admission, and result publication.  Abort callbacks are snapshotted under
    that lock and invoked only after it is released.
    """

    def __init__(
        self,
        limits: RequestTimeouts,
        *,
        clock: Callable[[], float] = time.monotonic,
        poll_s: float = 0.05,
        abort_grace_s: float = 0.25,
    ) -> None:
        if not isinstance(limits, RequestTimeouts):
            raise TypeError("limits must be RequestTimeouts")
        self.request_id = uuid.uuid4().hex
        self.limits = limits
        self.clock = clock
        self.poll_s = _positive_finite(poll_s, "poll_s")
        if isinstance(abort_grace_s, bool):
            raise ValueError("abort_grace_s must be finite and non-negative")
        try:
            self.abort_grace_s = float(abort_grace_s)
        except (TypeError, ValueError):
            raise ValueError("abort_grace_s must be finite and non-negative") from None
        if not math.isfinite(self.abort_grace_s) or self.abort_grace_s < 0:
            raise ValueError("abort_grace_s must be finite and non-negative")
        self.started_at = clock()
        self.first_event_at: float | None = None
        self.last_event_at: float | None = None

        self._state_lock = threading.Lock()
        self._terminal: str | None = None  # cancelled | watchdog | completed
        self._reason = ""
        self._aborters: list[Callable[[str], object]] = []
        self._registered_aborters: dict[tuple, Callable[[str], object]] = {}
        self._has_physical_abort = False

    @property
    def cancelled(self) -> bool:
        with self._state_lock:
            return self._terminal in ("cancelled", "watchdog")

    @property
    def reason(self) -> str:
        with self._state_lock:
            return self._reason

    @property
    def physical_abort_available(self) -> bool:
        """Whether a physical abort callback has been registered for this request."""
        with self._state_lock:
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
        with self._state_lock:
            if self._terminal is not None:
                return
            if self.first_event_at is None:
                self.first_event_at = now
            self.last_event_at = now

    def remaining(self) -> float | None:
        if self.limits.total_s is None:
            return None
        return max(0.0, self.limits.total_s - (self.clock() - self.started_at))

    @staticmethod
    def _callback_key(callback: Callable[[str], object]) -> tuple:
        owner = getattr(callback, "__self__", None)
        function = getattr(callback, "__func__", None)
        if owner is not None and function is not None:
            return ("bound", id(owner), function)
        return ("callable", id(callback))

    def register_abort(self, callback: Callable[[str], object]) -> None:
        """Register a physical abort callback and invoke it immediately if already cancelled.

        Bound methods are canonicalized by ``(__self__, __func__)`` so repeated
        attribute access registers one aborter.  Every callback runs outside the state
        lock, including callbacks registered after cancellation.
        """
        if not callable(callback):
            raise TypeError("request abort callback must be callable")

        invoke_now = False
        reason = ""
        with self._state_lock:
            key = self._callback_key(callback)
            if key in self._registered_aborters:
                return
            self._registered_aborters[key] = callback
            self._has_physical_abort = True
            if self._terminal in ("cancelled", "watchdog"):
                invoke_now = True
                reason = self._reason
            elif self._terminal is None:
                self._aborters.append(callback)
        if invoke_now:
            self._invoke_aborters((callback,), reason)

    def cancel(self, reason: str = "user") -> bool:
        """Win cancellation once and invoke the winning snapshot of aborters."""
        reason = reason or "user"
        with self._state_lock:
            if self._terminal is not None:
                return False
            self._terminal = "cancelled"
            self._reason = reason
            aborters = tuple(self._aborters)
            self._aborters.clear()
        self._invoke_aborters(aborters, reason)
        return True

    def _terminal_exception_locked(self):
        if self._terminal == "cancelled":
            return RequestCancelled(self._reason)
        if self._terminal == "watchdog":
            return RequestWatchdogTimeout(self._reason)
        return None

    def check(self) -> None:
        """Raise the first terminal exception, or atomically claim an expired watchdog."""
        now = self.clock()
        aborters: tuple[Callable[[str], object], ...] = ()
        exception = None
        with self._state_lock:
            exception = self._terminal_exception_locked()
            if exception is None and self._terminal is None:
                reason = None
                if self.limits.total_s is not None and now - self.started_at >= self.limits.total_s:
                    reason = "total"
                elif (self.first_event_at is None and self.limits.ttfb_s is not None
                      and now - self.started_at >= self.limits.ttfb_s):
                    reason = "ttfb"
                elif (self.last_event_at is not None and self.limits.idle_s is not None
                      and now - self.last_event_at >= self.limits.idle_s):
                    reason = "idle"
                if reason is not None:
                    self._terminal = "watchdog"
                    self._reason = reason
                    aborters = tuple(self._aborters)
                    self._aborters.clear()
                    exception = RequestWatchdogTimeout(reason)
        if aborters:
            self._invoke_aborters(aborters, self.reason)
        if exception is not None:
            raise exception

    def run(self, fn: Callable[[], object], *, cancel: Callable[[], bool] | None = None):
        """Run a callable while polling request state and publishing one terminal outcome."""
        self.check()
        with self._state_lock:
            exception = self._terminal_exception_locked()
            if exception is not None:
                raise exception
            if self._terminal is not None:
                raise RuntimeError("request context already completed")

        box: dict[str, object] = {}
        done = threading.Event()

        def worker() -> None:
            with self._state_lock:
                if self._terminal is not None:
                    done.set()
                    return
            try:
                outcome = (True, fn())
            except BaseException as exc:  # noqa: BLE001 — preserve the callable's exact failure
                outcome = (False, exc)
            with self._state_lock:
                # A cancellation that won before this write makes the late outcome
                # unpublishable; the caller will raise the stored terminal exception.
                box["outcome"] = outcome
            done.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        try:
            while not done.wait(self.poll_s):
                if cancel is not None and cancel():
                    self.cancel("user")
                self.check()
            if cancel is not None and cancel():
                self.cancel("user")
            self.check()

            # This is the result-publication linearization point.  Cancellation wins
            # if it acquired the state lock before this block.
            with self._state_lock:
                exception = self._terminal_exception_locked()
                if exception is not None:
                    raise exception
                outcome = box.get("outcome")
                if outcome is None:
                    raise RuntimeError("request worker completed without an outcome")
                self._terminal = "completed"
            ok, value = outcome
            if not ok:
                raise value
            return value
        except (RequestCancelled, RequestWatchdogTimeout):
            done.wait(self.abort_grace_s)
            raise

    @staticmethod
    def _invoke_aborters(aborters: tuple[Callable[[str], object], ...], reason: str) -> None:
        for abort in aborters:
            try:
                abort(reason)
            except Exception:  # noqa: BLE001 — one broken abort hook cannot block cancellation
                log.warning("request abort callback failed", exc_info=True)
