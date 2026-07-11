from __future__ import annotations

import threading

import pytest

import okami.llm.providers as providers
from okami.config import build_config
from okami.core import Harness, Task
from okami.llm.request import (
    RequestCancelled,
    RequestContext,
    RequestTimeouts,
    RequestWatchdogTimeout,
)


def test_cancel_aborts_inflight_request_and_does_not_fallback():
    started = threading.Event()
    released = threading.Event()
    worker_done = threading.Event()
    calls = []
    ctx = RequestContext(RequestTimeouts(total_s=10))

    cfg = build_config({
        "default_provider": "primary",
        "providers": {
            "primary": {"model": "primary-model", "fallback": ["fallback"]},
            "fallback": {"model": "fallback-model"},
        },
    })

    def fake_complete_one(pc, messages, model, schema, overrides, request=None, **kwargs):
        calls.append(pc.name)
        started.set()
        try:
            released.wait(1)
            raise RuntimeError("rate limit", 429)
        finally:
            worker_done.set()

    def abort(reason):
        assert reason == "user"
        released.set()

    ctx.register_abort(abort)
    def providers_complete():
        return providers.complete_messages_ex(
            cfg,
            [{"role": "user", "content": "oi"}],
            request=ctx,
        )

    result = {}

    def run_request():
        try:
            ctx.run(providers_complete)
        except BaseException as exc:  # observed below; this is the cancellation contract
            result["error"] = exc

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(providers, "_complete_one", fake_complete_one)
    try:
        thread = threading.Thread(target=run_request)
        thread.start()
        assert started.wait(0.2)
        ctx.cancel("user")
        thread.join(0.3)
        assert not thread.is_alive()
    finally:
        released.set()
        assert worker_done.wait(0.2)
        monkeypatch.undo()

    assert started.is_set()
    assert calls == ["primary"]
    assert isinstance(result["error"], RequestCancelled)


def test_request_run_returns_promptly_after_cancellation():
    started = threading.Event()
    released = threading.Event()
    done = threading.Event()
    ctx = RequestContext(RequestTimeouts(total_s=30), abort_grace_s=0.05)
    ctx.register_abort(lambda reason: released.set())

    def work():
        started.set()
        released.wait(1)
        done.set()

    result = {}

    def run():
        try:
            ctx.run(work)
        except BaseException as exc:  # worker is intentionally observed below
            result["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    assert started.wait(0.2)
    ctx.cancel("user")
    thread.join(0.3)

    assert not thread.is_alive()
    assert isinstance(result["error"], RequestCancelled)
    assert done.wait(0.2)


def test_watchdog_timeout_does_not_enter_provider_fallback():
    now = [100.0]
    calls = []
    ctx = RequestContext(RequestTimeouts(total_s=1), clock=lambda: now[0])
    cfg = build_config({
        "default_provider": "primary",
        "providers": {
            "primary": {"model": "primary-model", "fallback": ["fallback"]},
            "fallback": {"model": "fallback-model"},
        },
    })

    def fake_complete_one(pc, messages, model, schema, overrides, request=None, **kwargs):
        calls.append(pc.name)
        now[0] += 1.1
        raise RuntimeError("rate limit")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(providers, "_complete_one", fake_complete_one)
    try:
        with pytest.raises(RequestWatchdogTimeout, match="total"):
            providers.complete_messages_ex(
                cfg,
                [{"role": "user", "content": "oi"}],
                request=ctx,
            )
    finally:
        monkeypatch.undo()

    assert calls == ["primary"]


def test_legacy_generate_callable_without_request_still_works(tmp_path):
    task = Harness(
        lambda messages, schema: '{"tool":"respond","args":{"message":"ok"}}',
        Task(goal="oi"),
        tmp_path,
    ).run()
    assert task.result == "ok"


def test_request_cancellation_bypasses_harness_retry_and_escalation(tmp_path):
    calls = []
    escalations = []
    events = []

    def generate(messages, schema):
        calls.append("generate")
        raise RequestCancelled("user")

    def cancel():
        return bool(calls)

    def escalate(messages, schema):
        escalations.append("escalate")
        return '{"tool":"respond","args":{"message":"should not run"}}'

    task = Harness(generate, Task(goal="oi"), tmp_path,
                   cancel=cancel, escalate=escalate, on_event=events.append).run()

    assert task.state.value == "BLOCKED"
    assert calls == ["generate"]
    assert escalations == []
    assert not any(event.get("kind") == "failure" for event in events)
    assert not any(event.get("kind") == "escalate" for event in events)
