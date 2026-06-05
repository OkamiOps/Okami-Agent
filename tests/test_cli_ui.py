"""Design-system da CLI (okami/cli/_ui.py): primitivas de layout renderizam e compõem sem quebrar."""

from __future__ import annotations

from rich.console import Console

from okami.cli import _ui


def _render(renderable, width: int = 120) -> str:
    """Renderiza um renderable do Rich p/ string (sem cor) — p/ asserir o conteúdo visível."""
    con = Console(width=width, file=None, record=True, color_system=None)
    con.print(renderable)
    return con.export_text()


def test_masthead_has_brand_version_and_right():
    out = _render(_ui.masthead("0.0.1", right="status"))
    assert "OKAMI" in out and "v0.0.1" in out and "status" in out
    assert "╭" in out and "╮" in out                  # emoldurado (Panel)


def test_meter_fills_by_ratio_and_clamps():
    full = _render(_ui.meter(1.0, width=10))
    half = _render(_ui.meter(0.5, width=10))
    empty = _render(_ui.meter(0.0, width=10))
    assert full.count("█") == 10 and "░" not in full.strip()
    assert half.count("█") == 5 and half.count("░") == 5
    assert empty.count("█") == 0 and empty.count("░") == 10
    # fora de [0,1] não estoura a barra
    assert _render(_ui.meter(9.0, width=8)).count("█") == 8
    assert _render(_ui.meter(-3.0, width=8)).count("█") == 0


def test_meter_rows_renders_label_value_flag():
    rows = [("tool_outputs", 1.0, "87 KB", _ui.badge("warn", "quota")),
            ("checkpoints", 0.1, "5 KB", "")]
    out = _render(_ui.meter_rows(rows, bar_width=10, label_w=12))
    assert "tool_outputs" in out and "87 KB" in out and "quota" in out and "█" in out


def test_grid_two_columns_wide_one_column_narrow():
    cards = [_ui.panel(_ui.fields([("k", "v")]), title="A"),
             _ui.panel(_ui.fields([("k", "v")]), title="B")]
    wide = _render(_ui.grid(cards, width=120))
    narrow = _render(_ui.grid(cards, width=70))
    assert "A" in wide and "B" in wide
    # largo: A e B na MESMA linha (lado a lado); estreito: A antes de B em linhas separadas
    wide_lines = [ln for ln in wide.splitlines() if "◆ A" in ln or "◆ B" in ln]
    assert any("A" in ln and "B" in ln for ln in wide_lines)         # 2 colunas
    assert narrow.index("◆ A") < narrow.index("◆ B")                 # empilhado


def test_panel_carries_title_and_accent_border():
    out = _render(_ui.panel(_ui.fields([("modelo", "openai/x")]), title="Sessão"))
    assert "Sessão" in out and "openai/x" in out and "◆" in out


def test_rule_with_title():
    assert "Disco" in _render(_ui.rule("Disco"))
