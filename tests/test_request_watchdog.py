from __future__ import annotations

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
