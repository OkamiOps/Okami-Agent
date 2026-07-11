from __future__ import annotations

import math
import threading

import pytest

from okami.llm.request import (
    RequestCancelled,
    RequestContext,
    RequestTimeouts,
    RequestWatchdogTimeout,
)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def fake_clock():
    return FakeClock()


def test_ttfb_expires_before_first_event(fake_clock):
    ctx = RequestContext(RequestTimeouts(total_s=30, ttfb_s=2, idle_s=5), clock=fake_clock)
    fake_clock.advance(2.1)
    with pytest.raises(RequestWatchdogTimeout, match="ttfb"):
        ctx.check()


def test_idle_expires_after_first_event(fake_clock):
    ctx = RequestContext(RequestTimeouts(total_s=30, ttfb_s=2, idle_s=5), clock=fake_clock)
    ctx.observe()
    fake_clock.advance(5.1)
    with pytest.raises(RequestWatchdogTimeout, match="idle"):
        ctx.check()


def test_total_remaining_is_shared_by_the_request(fake_clock):
    ctx = RequestContext(RequestTimeouts(total_s=3), clock=fake_clock)
    fake_clock.advance(2)
    assert ctx.remaining() == pytest.approx(1)
    fake_clock.advance(1.1)
    with pytest.raises(RequestWatchdogTimeout, match="total"):
        ctx.check()


def test_cancel_invokes_aborters_once_and_outside_the_lock():
    calls = []
    callback_finished = threading.Event()
    ctx = RequestContext(RequestTimeouts(total_s=30, ttfb_s=None, idle_s=None))

    def abort(reason):
        # Re-entering the context must not deadlock if callbacks are outside the lock.
        calls.append((reason, ctx.remaining()))
        callback_finished.set()

    ctx.register_abort(abort)
    ctx.cancel("user")
    ctx.cancel("user")

    assert callback_finished.wait(0.2)
    assert calls == [("user", pytest.approx(30, abs=1))]
    with pytest.raises(RequestCancelled, match="user"):
        ctx.check()


def test_register_abort_after_cancel_invokes_callback_once():
    calls = []
    ctx = RequestContext(RequestTimeouts())
    ctx.cancel("user")
    ctx.register_abort(calls.append)
    ctx.cancel("again")
    assert calls == ["user"]


def test_context_exposes_physical_abort_limitation_honestly():
    ctx = RequestContext(RequestTimeouts(total_s=3))
    assert ctx.physical_abort_available is False
    assert "no physical abort handle" in ctx.abort_limitation
    ctx.register_abort(lambda reason: None)
    assert ctx.physical_abort_available is True
    assert ctx.abort_limitation is None


def test_watchdog_race_preserves_first_user_cancellation_reason():
    """A cancellation that wins while ``check`` samples the clock owns the exception type."""
    holder = {}
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        if calls == 2:  # RequestContext.__init__ sampled once; check() samples here.
            holder["ctx"].cancel("user")
        return 100.0 if calls == 1 else 101.1

    holder["ctx"] = RequestContext(RequestTimeouts(total_s=1), clock=clock)
    with pytest.raises(RequestCancelled, match="user"):
        holder["ctx"].check()
    with pytest.raises(RequestCancelled, match="user"):
        holder["ctx"].check()


def test_repeated_bound_method_registration_aborts_once():
    class Aborter:
        def __init__(self):
            self.reasons = []

        def abort(self, reason):
            self.reasons.append(reason)

    aborter = Aborter()
    ctx = RequestContext(RequestTimeouts())
    ctx.register_abort(aborter.abort)
    ctx.register_abort(aborter.abort)
    ctx.cancel("user")
    assert aborter.reasons == ["user"]


@pytest.mark.parametrize("value", [0, -1, math.nan, math.inf, "not-a-number"])
def test_request_limits_reject_non_positive_or_non_finite_values(value):
    with pytest.raises(ValueError):
        RequestTimeouts(total_s=value)


def test_cancel_before_worker_start_prevents_callable_execution(monkeypatch):
    started = threading.Event()
    ctx = RequestContext(RequestTimeouts(total_s=30))
    real_start = threading.Thread.start

    def start_and_cancel(thread):
        ctx.cancel("user")
        real_start(thread)

    monkeypatch.setattr(threading.Thread, "start", start_and_cancel)
    with pytest.raises(RequestCancelled, match="user"):
        ctx.run(lambda: started.set())
    assert not started.is_set()


def test_cancellation_after_final_check_cannot_publish_worker_result(monkeypatch):
    ctx = RequestContext(RequestTimeouts(total_s=30))
    real_check = ctx.check
    checks = 0

    def check_then_cancel_before_publication():
        nonlocal checks
        checks += 1
        real_check()
        if checks == 2:  # final check passed; publication must still arbitrate atomically.
            ctx.cancel("user")

    monkeypatch.setattr(ctx, "check", check_then_cancel_before_publication)
    with pytest.raises(RequestCancelled, match="user"):
        ctx.run(lambda: "late result")
