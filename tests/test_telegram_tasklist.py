"""Paridade Hermes (task lists, adaptado ao HTML do Okami): listas de tarefa GFM (- [ ] / - [x]) renderizavam
com o checkbox LITERAL ('• [ ] tarefa'). Agora viram caixinhas ☐/☑ — legível no Telegram, sem precisar da
rich-message API (que o próprio autor do Hermes recomenda DESLIGADA). Bullets normais seguem virando •."""
from __future__ import annotations

from okami.channels.markdown_telegram import to_html


def test_unchecked_and_checked_become_boxes():
    out = to_html("- [ ] fazer X\n- [x] feito Y")
    assert "☐ fazer X" in out and "☑ feito Y" in out
    assert "[ ]" not in out and "[x]" not in out


def test_uppercase_X_also_checked():
    assert "☑ ok" in to_html("- [X] ok")


def test_normal_bullet_still_dot():
    out = to_html("- item normal")
    assert "• item normal" in out and "☐" not in out
