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


def test_inflight_watchdog_aborts_once_returns_promptly_and_does_not_retry_or_fallback():
    """The real in-flight watchdog path is barrier-controlled, not sleep-controlled."""
    started = threading.Event()
    released = threading.Event()
    finished = threading.Event()
    now = [100.0]
    calls = []
    aborts = []
    ctx = RequestContext(RequestTimeouts(total_s=1), clock=lambda: now[0], poll_s=0.005,
                         abort_grace_s=0.05)
    cfg = build_config({
        "default_provider": "primary",
        "providers": {
            "primary": {"model": "primary-model", "fallback": ["fallback"], "max_retries": 3},
            "fallback": {"model": "fallback-model"},
        },
    })

    def fake_complete_one(pc, messages, model, schema, overrides, request=None, **kwargs):
        calls.append(pc.name)
        request.register_abort(lambda reason: (aborts.append(reason), released.set()))
        started.set()
        released.wait(1)
        finished.set()
        return '{"tool":"respond","args":{"message":"late"}}'

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(providers, "_complete_one", fake_complete_one)
    result = {}

    def run():
        try:
            ctx.run(lambda: providers.complete_messages_ex(
                cfg, [{"role": "user", "content": "oi"}], request=ctx))
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=run)
    try:
        thread.start()
        assert started.wait(0.2)
        now[0] = 102.0
        thread.join(0.3)
        assert not thread.is_alive()
    finally:
        released.set()
        thread.join(0.3)
        monkeypatch.undo()

    assert isinstance(result["error"], RequestWatchdogTimeout)
    assert calls == ["primary"]
    assert aborts == ["total"]
    assert finished.wait(0.2)


def test_legacy_provider_callable_without_request_is_invoked_without_keyword(monkeypatch):
    cfg = build_config({"default_provider": "p", "providers": {"p": {"model": "m", "max_retries": 1}}})
    calls = []

    def legacy(pc, messages, model, schema, overrides):
        calls.append(pc.name)
        return '{"tool":"respond","args":{"message":"ok"}}'

    monkeypatch.setattr(providers, "_complete_one", legacy)
    result = providers.complete_messages_ex(cfg, [{"role": "user", "content": "oi"}],
                                           request=RequestContext(RequestTimeouts(total_s=10)))
    assert result.text.endswith('"ok"}}')
    assert calls == ["p"]


def test_optional_request_adapter_does_not_swallow_provider_typeerror():
    def provider(request):
        raise TypeError("provider body failure")

    with pytest.raises(TypeError, match="provider body failure"):
        providers._invoke_with_optional_request(provider, request=RequestContext(RequestTimeouts()))


def test_provider_body_typeerror_is_not_retried(monkeypatch):
    cfg = build_config({"default_provider": "p", "providers": {"p": {"model": "m", "max_retries": 3}}})
    calls = []

    def provider(pc, messages, model, schema, overrides, request=None):
        calls.append(1)
        raise TypeError("provider body failure")

    monkeypatch.setattr(providers, "_complete_one", provider)
    with pytest.raises(TypeError, match="provider body failure"):
        providers.complete_messages_ex(cfg, [{"role": "user", "content": "oi"}],
                                       request=RequestContext(RequestTimeouts(total_s=10)))
    assert calls == [1]


def test_cancel_racing_ordinary_provider_error_bypasses_harness_recovery(tmp_path):
    started = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    events = []
    calls = []

    def generate(messages, schema):
        calls.append("generate")
        started.set()
        release.wait(1)
        raise RuntimeError("ordinary provider error")

    def cancel():
        return cancelled.is_set()

    def escalate(messages, schema):
        calls.append("escalate")
        return '{"tool":"respond","args":{"message":"bad recovery"}}'

    task_box = {}

    def run():
        task_box["task"] = Harness(generate, Task(goal="oi"), tmp_path,
                                    cancel=cancel, escalate=escalate,
                                    on_event=events.append).run()

    thread = threading.Thread(target=run)
    thread.start()
    assert started.wait(0.2)
    cancelled.set()
    release.set()
    thread.join(0.5)

    assert not thread.is_alive()
    assert task_box["task"].state.value == "BLOCKED"
    assert calls == ["generate"]
    assert not any(event.get("kind") == "failure" for event in events)
    assert not any(event.get("kind") == "escalate" for event in events)


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


def test_runner_creates_fresh_request_context_for_each_generation(tmp_path, monkeypatch):
    from okami.runner import run_task
    from okami.llm.usage import Completion

    cfg = build_config({"default_provider": "p", "providers": {"p": {"model": "m", "max_retries": 1}}})
    seen = []

    def fake_complete(cfg, messages, request=None, **kwargs):
        seen.append((request.request_id, request.first_event_at, request.last_event_at))
        request.observe()
        if len(seen) == 1:
            text = '```json\n{"tool":"list_dir","args":{"path":"."}}\n```'
        else:
            text = '```json\n{"tool":"respond","args":{"message":"ok"}}\n```'
        return Completion(text=text, provider="p", model="m")

    monkeypatch.setattr(providers, "complete_messages_ex", fake_complete)
    task = run_task(cfg, tmp_path, "oi", surface="cli")

    assert task.state.value == "COMPLETE"
    assert len(seen) == 2
    assert seen[0][0] != seen[1][0]
    assert seen[0][1:] == (None, None)
    assert seen[1][1:] == (None, None)


def test_runner_legacy_provider_double_without_request_still_works(tmp_path, monkeypatch):
    from okami.runner import run_task
    from okami.llm.usage import Completion

    cfg = build_config({"default_provider": "p", "providers": {"p": {"model": "m", "max_retries": 1}}})

    def legacy(cfg, messages, *, provider=None, model=None, response_schema=None,
               cancel=None, on_heartbeat=None):
        return Completion(text='```json\n{"tool":"respond","args":{"message":"ok"}}\n```',
                          provider="p", model="m")

    monkeypatch.setattr(providers, "complete_messages_ex", legacy)
    task = run_task(cfg, tmp_path, "oi", surface="cli")
    assert task.state.value == "COMPLETE"
