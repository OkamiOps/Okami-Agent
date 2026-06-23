"""TUI: diff colorido em edição de arquivo + preview de saída no tool-call (paridade Hermes).

Antes o tool-call era 1 linha seca e a edição de arquivo não mostrava o QUE mudou. Agora edit_file
vira um card com diff verde/vermelho, e tools de leitura/shell ganham preview da saída (modo expanded)."""

from __future__ import annotations

from rich.console import Console

import okami.tui as tui


def _render(obj) -> str:
    """Renderiza um renderable do Rich p/ texto puro (inspeção em teste, sem TTY)."""
    c = Console(width=80, no_color=True, file=open("/dev/null", "w"))
    with c.capture() as cap:
        c.print(obj)
    return cap.get()


# ----------------------------------------------------------------- diff_block (pura)
def test_diff_block_marks_added_and_removed():
    d = tui.diff_block("linha um\nlinha dois\n", "linha um\nlinha DOIS\n", path="x.py")
    out = _render(d)
    assert "x.py" in out
    assert "- linha dois" in out and "+ linha DOIS" in out
    assert "  linha um" in out                            # contexto inalterado sem marca +/-


def test_diff_block_new_file_shows_all_added():
    d = tui.diff_block("", "a\nb\n", path="novo.txt")
    out = _render(d)
    assert "+ a" in out and "+ b" in out
    assert "- " not in out                                # arquivo novo: só adições


def test_diff_block_caps_huge_diff():
    big_old = "\n".join(f"l{i}" for i in range(500))
    big_new = "\n".join(f"L{i}" for i in range(500))
    out = _render(tui.diff_block(big_old, big_new, path="big"))
    assert "…" in out or "truncado" in out.lower()        # diff gigante é capado, não despeja 1000 linhas


# ----------------------------------------------------------------- tool_block: edit → diff
def test_tool_block_edit_file_renders_diff():
    e = {"kind": "step", "tool": "edit_file", "ok": True,
         "args": {"path": "app.py", "old": "x = 1", "new": "x = 2"}, "out": "ok"}
    out = _render(tui.tool_block(e, "collapsed"))
    assert "edit_file" in out and "app.py" in out
    assert "- x = 1" in out and "+ x = 2" in out          # o diff aparece no card


def test_tool_block_write_file_shows_new_content():
    e = {"kind": "step", "tool": "write_file", "ok": True,
         "args": {"path": "novo.py", "content": "print('oi')\n"}, "out": "escrito"}
    out = _render(tui.tool_block(e, "collapsed"))
    assert "novo.py" in out and "print('oi')" in out


def test_tool_block_read_preview_by_default_short_collapsed():
    # paridade Hermes: a caixa de resultado aparece POR PADRÃO (collapsed), só mais curta que no expanded.
    e = {"kind": "step", "tool": "read_file", "ok": True,
         "args": {"path": "a.txt"}, "out": "L1\nL2\nL3\nL4\nL5\nL6"}
    exp = _render(tui.tool_block(e, "expanded"))
    col = _render(tui.tool_block(e, "collapsed"))
    assert "L1" in exp and "L6" in exp                    # expanded mostra até 12 linhas
    assert "L1" in col                                    # collapsed JÁ mostra o resultado (antes: só no expanded)
    assert "L6" not in col                                # …mas capado curto (3 linhas)


def test_tool_block_non_step_falls_back_to_event_line():
    e = {"kind": "loop", "repeats": 3}
    # eventos não-step não têm card especial → mesmo texto do event_line
    assert _render(tui.tool_block(e, "collapsed")) == _render(tui.event_line(e, "collapsed"))


def test_tool_block_hidden_suppresses_step():
    e = {"kind": "step", "tool": "read_file", "ok": True, "args": {"path": "a"}, "out": "x"}
    assert tui.tool_block(e, "hidden") is None
