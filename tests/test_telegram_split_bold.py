"""Telegram feio (hunt#2): quando uma resposta longa (>4000) é partida NO MEIO de um **negrito**, a parte
fica com `**` sem par → o Telegram mostra `**` LITERAL (e a próxima parte um `**` órfão). Agora o split
fecha o `**` na parte e REABRE na próxima (espelha o que já fazia com blocos ```), pra cada parte renderizar
sozinha."""
from __future__ import annotations

from okami.channels.markdown_telegram import to_html
from okami.channels.telegram import _split_message


def test_long_bold_span_does_not_leak_literal_asterisks():
    text = "**" + ("palavra " * 800) + "**"          # um único negrito gigante (~6400 chars) → split no meio
    parts = _split_message(text, 4000)
    assert len(parts) > 1
    for p in parts:
        # cada parte, renderizada, NÃO pode deixar `**` literal (= negrito quebrado)
        assert "**" not in to_html(p), f"** literal vazou na parte: {p[:60]!r}…"


def test_short_message_unchanged():
    assert _split_message("oi **tudo bem?**", 4000) == ["oi **tudo bem?**"]
