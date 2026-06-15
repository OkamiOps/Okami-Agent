"""Item 1 (#8): tool `clarify` — o agente PERGUNTA ao dono antes de agir em ambiguidade.

Pura aqui (hook `ctx.clarify` injetado). O bloqueio thread-safe no gateway é testado à parte."""
from __future__ import annotations

from pathlib import Path


def test_clarify_returns_owner_answer():
    from okami.core.tools import ToolContext
    from okami.core.tools.clarify import Clarify
    seen = {}

    def hook(q, opts):
        seen["q"], seen["opts"] = q, opts
        return "opção B"
    ctx = ToolContext(workspace=Path("."), clarify=hook)
    r = Clarify().run({"question": "A ou B?", "options": "A|B"}, ctx)
    assert r.ok and "opção B" in r.output
    assert seen["q"] == "A ou B?" and seen["opts"] == ["A", "B"]


def test_clarify_fails_soft_without_owner():
    # Sem dono interativo (cron/autônomo): NÃO trava — devolve fail-soft mandando seguir com default.
    from okami.core.tools import ToolContext
    from okami.core.tools.clarify import Clarify
    r = Clarify().run({"question": "qual repo?"}, ToolContext(workspace=Path(".")))
    assert not r.ok and "default" in r.output.lower()


def test_clarify_fails_soft_on_timeout():
    from okami.core.tools import ToolContext
    from okami.core.tools.clarify import Clarify
    ctx = ToolContext(workspace=Path("."), clarify=lambda q, o: None)   # sem resposta (timeout)
    r = Clarify().run({"question": "qual?"}, ctx)
    assert not r.ok and "default" in r.output.lower()


def test_clarify_requires_question():
    from okami.core.tools import ToolContext
    from okami.core.tools.clarify import Clarify
    r = Clarify().run({"question": "  "}, ToolContext(workspace=Path("."), clarify=lambda q, o: "x"))
    assert not r.ok


def test_parse_options_pipe_and_list():
    from okami.core.tools.clarify import parse_options
    assert parse_options("a | b |c") == ["a", "b", "c"]
    assert parse_options(["x", "y"]) == ["x", "y"]
    assert parse_options(None) == []
    assert parse_options("") == []


def test_clarify_in_default_registry():
    from okami.core.tools import default_registry
    assert "clarify" in default_registry()
