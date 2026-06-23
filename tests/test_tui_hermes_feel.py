"""Paridade de TERMINAL com o Hermes (ui-tui/Ink) no TUI Python (Textual/Rich).

O que o Hermes faz e o Okami não fazia, agora portado como helpers PUROS (testáveis sem subir a tela):
- indicador VIVO de tool rodando (spinner + emoji + nome + relógio) — antes a linha só aparecia DEPOIS;
- verbo/face que ROTACIONA enquanto pensa (FaceTicker do Hermes) — antes "raciocinando…" fixo;
- preview da saída por PADRÃO (Hermes sempre mostra a caixa de resultado) — antes só no /details expanded;
- histórico ↑/↓ do input (recall das mensagens) — antes o TUI não tinha.
"""
from __future__ import annotations

from okami import tui


def _plain(renderable) -> str:
    from rich.console import Console
    c = Console(width=100, file=__import__("io").StringIO(), color_system=None)
    c.print(renderable)
    return c.file.getvalue()


# ---------------------------------------------------------------- verbo rotativo (FaceTicker)
def test_thinking_phrase_rotates_and_cycles():
    seen = {tui.thinking_phrase(i) for i in range(400)}
    assert len(seen) > 1                                   # NÃO é fixo — rotaciona
    assert all(isinstance(p, str) and p for p in seen)     # sempre string não-vazia
    assert tui.thinking_phrase(0) == tui.thinking_phrase(len(tui._THINK_VERBS) * tui._THINK_EVERY)  # cicla


# ---------------------------------------------------------------- linha de tool RODANDO (live)
def test_running_tool_text_has_emoji_name_and_clock():
    t = tui.running_tool_text("read_file", {"path": "a.py"}, spin="⠙", elapsed=3)
    s = t.plain
    assert "read_file" in s and "3s" in s and "⠙" in s
    assert "📖" in s                                       # emoji do tipo de tool (read → 📖)
    assert "a.py" in s                                     # preview do arg


# ---------------------------------------------------------------- preview da saída POR PADRÃO
def test_tool_block_shows_short_output_preview_at_collapsed():
    e = {"kind": "step", "tool": "read_file", "args": {"path": "a.py"}, "ok": True,
         "out": "linha1\nlinha2\nlinha3\nlinha4\nlinha5"}
    txt = _plain(tui.tool_block(e, "collapsed"))
    assert "linha1" in txt                                 # mostra o resultado SEM precisar de /details
    assert "linha4" not in txt                             # mas capado curto (3 linhas) no collapsed


def test_tool_block_collapsed_preview_truncation_marker():
    e = {"kind": "step", "tool": "run_shell", "args": {"cmd": "ls"}, "ok": True,
         "out": "a\nb\nc\nd\ne\nf"}
    txt = _plain(tui.tool_block(e, "collapsed"))
    assert "+3" in txt or "…" in txt                       # indica que há mais (não finge que mostrou tudo)


def test_tool_block_write_still_shows_code_not_outdump():
    # write/edit mantêm o preview RICO (código/diff), não o dump de saída
    e = {"kind": "step", "tool": "write_file", "args": {"path": "x.py", "content": "print(1)"}, "ok": True,
         "out": "ok"}
    txt = _plain(tui.tool_block(e, "collapsed"))
    assert "print(1)" in txt


# ---------------------------------------------------------------- histórico ↑/↓ do input
def test_input_history_recall_up_and_down():
    h = tui.InputHistory()
    h.add("primeiro")
    h.add("segundo")
    assert h.prev() == "segundo"                           # ↑ → mais recente
    assert h.prev() == "primeiro"                          # ↑ → anterior
    assert h.prev() == "primeiro"                          # topo: para (não estoura)
    assert h.next() == "segundo"                           # ↓ → mais recente
    assert h.next() == ""                                  # ↓ além do fim → linha nova (vazia)


def test_fmt_elapsed_formats():
    assert tui.fmt_elapsed(0) == "0s"
    assert tui.fmt_elapsed(45) == "45s"
    assert tui.fmt_elapsed(90) == "1m 30s"
    assert tui.fmt_elapsed(3661) == "1h 1m"
    assert tui.fmt_elapsed(-5) == "0s"                     # nunca negativo


def test_input_history_skips_empty_and_consecutive_dups():
    h = tui.InputHistory()
    h.add("x")
    h.add("")                                              # vazio: ignora
    h.add("x")                                             # dup consecutiva: ignora
    h.add("y")
    assert h.prev() == "y"
    assert h.prev() == "x"
    assert h.prev() == "x"                                 # só um 'x'
