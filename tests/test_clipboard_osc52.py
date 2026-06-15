"""Item 6 (#8): copiar via OSC-52 — funciona ATRAVÉS de SSH/tmux, onde não há clipboard nativo.
O REPL (--no-tui) ganha /copy de verdade (antes mandava "selecione com o mouse", que quebra no SSH)."""
from __future__ import annotations

import base64
import io


def test_osc52_copy_encodes_base64():
    from okami.core.clipboard import osc52_copy
    seq = osc52_copy("hello", tmux=False)
    assert seq.startswith("\x1b]52;c;") and seq.endswith("\x07")
    payload = seq[len("\x1b]52;c;"):-1]
    assert base64.b64decode(payload).decode("utf-8") == "hello"


def test_osc52_copy_wraps_for_tmux():
    from okami.core.clipboard import osc52_copy
    seq = osc52_copy("x", tmux=True)
    assert seq.startswith("\x1bPtmux;") and seq.endswith("\x1b\\")   # DCS passthrough do tmux


def test_osc52_copy_handles_unicode():
    from okami.core.clipboard import osc52_copy
    seq = osc52_copy("café ☕", tmux=False)
    payload = seq[len("\x1b]52;c;"):-1]
    assert base64.b64decode(payload).decode("utf-8") == "café ☕"


def test_copy_to_terminal_writes_sequence():
    from okami.core.clipboard import copy_to_terminal
    buf = io.StringIO()
    copy_to_terminal("abc", out=buf, tmux=False)
    assert "\x1b]52;c;" in buf.getvalue()


def test_repl_copy_text_last_agent_reply():
    from okami.core.clipboard import repl_copy_text
    hist = [("USER", "oi"), ("AGENT", "olá"), ("USER", "tchau"), ("AGENT", "até")]
    text, label = repl_copy_text(hist, "")
    assert text == "até" and "última" in label


def test_repl_copy_text_whole_chat():
    from okami.core.clipboard import repl_copy_text
    hist = [("USER", "oi"), ("AGENT", "olá")]
    text, label = repl_copy_text(hist, "all")
    assert "oi" in text and "olá" in text and label == "conversa inteira"


def test_repl_copy_text_empty_when_no_reply():
    from okami.core.clipboard import repl_copy_text
    text, _ = repl_copy_text([("USER", "oi")], "")
    assert text == ""
