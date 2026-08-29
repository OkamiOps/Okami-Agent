"""Regression coverage for the gateway no-interrupt contract."""
from __future__ import annotations

import pytest


def _recorder():
    calls: list[bool] = []
    return calls, lambda value: calls.append(bool(value))


def test_harness_toggles_no_interrupt_during_compaction(tmp_path, monkeypatch):
    from okami.core import Harness, Task
    from okami.memory import compaction

    calls, hook = _recorder()
    harness = Harness(lambda *args, **kwargs: "ok", Task(goal="oi"), tmp_path,
                      set_no_interrupt=hook)
    monkeypatch.setattr(compaction, "compact",
                        lambda messages, memory, keep_tail=6, **kwargs: (messages, 0))

    harness._compact()

    assert calls == [True, False]


def test_harness_releases_no_interrupt_when_compaction_fails(tmp_path, monkeypatch):
    from okami.core import Harness, Task
    from okami.memory import compaction

    calls, hook = _recorder()
    harness = Harness(lambda *args, **kwargs: "ok", Task(goal="oi"), tmp_path,
                      set_no_interrupt=hook)

    def fail(*args, **kwargs):
        raise RuntimeError("compact failed")

    monkeypatch.setattr(compaction, "compact", fail)

    with pytest.raises(RuntimeError, match="compact failed"):
        harness._compact()

    assert calls[-1] is False


def test_harness_no_interrupt_defaults_to_noop(tmp_path):
    from okami.core import Harness, Task

    harness = Harness(lambda *args, **kwargs: "ok", Task(goal="oi"), tmp_path)
    harness._set_no_interrupt(True)


def test_harness_toggles_no_interrupt_around_spawn(tmp_path):
    from okami.core import Harness, Task

    calls, hook = _recorder()
    during: list[list[bool]] = []

    def spawn(goal, agent=None, model=None):
        during.append(list(calls))
        return "sub-ok"

    harness = Harness(lambda *args, **kwargs: "ok", Task(goal="oi"), tmp_path,
                      spawn=spawn, set_no_interrupt=hook)

    assert harness.ctx.spawn("faz aí", None, None) == "sub-ok"
    assert during == [[True]]
    assert calls == [True, False]


def test_harness_does_not_wrap_spawn_without_hook(tmp_path):
    from okami.core import Harness, Task

    def spawn(goal, agent=None, model=None):
        return "sub-ok"

    harness = Harness(lambda *args, **kwargs: "ok", Task(goal="oi"), tmp_path, spawn=spawn)

    assert harness.ctx.spawn is spawn
