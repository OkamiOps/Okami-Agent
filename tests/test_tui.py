"""TUI do chat (§13): banner, painel de tools/skills e status bar renderizam sem quebrar."""

from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console

from okami import tui


class _Skill:                       # stub leve (mesma interface usada por tui)
    def __init__(self, name, triggers=None, meta=None):
        self.name = name
        self.triggers = triggers or []
        self.meta = meta or {}


def _render(renderable) -> str:
    buf = io.StringIO()
    Console(width=100, file=buf, force_terminal=True, color_system="truecolor",
            legacy_windows=False).print(renderable)
    return buf.getvalue()


def test_welcome_has_logo_panel_tools_and_skills():
    tools = ["read_file", "write_file", "run_shell", "spawn", "browse", "generate_image", "task_complete"]
    skills = [_Skill("frontend-shadcn", ["design", "ui"]), _Skill("delegate-codex", ["codex"]),
              _Skill("humanizer", ["comunicar"])]
    out = _render(tui.welcome(version="1.2.3", model="qwen", provider="lmstudio · local",
                              cwd=Path("/x"), session="S1", agent="Okami", tools=tools,
                              skills=skills, resumed=2))
    assert "OKAMI" not in out          # logo é blocos █, não a palavra
    assert "█" in out                  # logo renderizou
    assert "Okami Agent" in out and "v1.2.3" in out
    assert "Ferramentas" in out and "arquivos" in out and "run_shell" in out
    assert "Skills" in out and "creative" in out and "frontend-shadcn" in out   # categoria inferida
    assert "task_complete" not in out  # tools de controle são ocultadas
    assert "7 ferramentas" in out and "3 skills" in out
    assert "retomando" in out          # resumed=2


def test_skill_category_inference_and_frontmatter_override():
    assert tui._skill_category(_Skill("frontend-shadcn", ["design"])) == "creative"
    assert tui._skill_category(_Skill("delegate-codex", ["codex"])) == "agents"
    assert tui._skill_category(_Skill("honcho-memory", ["memory"])) == "memory"
    assert tui._skill_category(_Skill("xyz", [], {"category": "custom"})) == "custom"
    assert tui._skill_category(_Skill("zzz-unknown", [])) == "geral"


def test_status_bar_gauge_scales_with_ctx():
    low = _render(tui.status_bar(model="m", ctx_pct=10, turns=1, elapsed=2))
    high = _render(tui.status_bar(model="m", ctx_pct=95, turns=9, elapsed=0))
    assert "10%" in low and "1 trocas" in low
    assert "95%" in high
    assert low.count("█") < high.count("█")     # barra enche conforme o contexto


def test_help_table_lists_core_commands():
    out = _render(tui.help_table())
    for c in ("/help", "/new", "/feedback", "/persona", "/exit", "/think"):
        assert c in out


def test_event_line_renders_steps_and_skips_noise():
    step = tui.event_line({"kind": "step", "tool": "read_file", "args": {"path": "foo.py"}, "ok": True})
    assert step is not None and "read_file" in _render(step) and "foo.py" in _render(step)
    loop = tui.event_line({"kind": "loop", "repeats": 3})
    assert loop is not None and "loop" in _render(loop).lower()
    assert tui.event_line({"kind": "start", "goal": "x"}) is None       # ruído: não mostra no chat
    assert tui.event_line({"kind": "complete", "summary": "y"}) is None  # a resposta já vai pelo canal
