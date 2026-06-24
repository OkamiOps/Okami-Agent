"""Telegram (auditoria Hermes): tabela/lista mostrada DENTRO de um bloco ```código``` (exemplo de código)
era convertida em bullet/'rótulo: valor' → o exemplo virava lixo. Agora o código é protegido ANTES da
conversão. + citação longa vira expandable (colapsa no celular)."""
from __future__ import annotations

from okami.channels.markdown_telegram import to_html


def test_table_inside_code_fence_stays_literal():
    md = "Exemplo:\n```\n| a | b |\n|---|---|\n| 1 | 2 |\n```"
    out = to_html(md)
    assert "| a | b |" in out                       # tabela DENTRO do código fica LITERAL
    assert "rótulo" not in out and "•" not in out    # NÃO virou bullet/kv


def test_bullet_inside_code_fence_stays_literal():
    md = "```\n- item de codigo\n- outro\n```"
    out = to_html(md)
    assert "- item de codigo" in out                 # hífen dentro do código NÃO vira •
    assert "•" not in out


def test_real_table_outside_code_still_converts():
    md = "| Col1 | Col2 |\n|---|---|\n| x | y |"
    out = to_html(md)
    assert "•" in out and "Col1" in out              # tabela de verdade (fora de código) ainda vira bullets


def test_long_quote_is_expandable():
    md = "> linha1\n> linha2\n> linha3\n> linha4\n> linha5"
    out = to_html(md)
    assert "<blockquote expandable>" in out          # citação longa colapsa


def test_short_quote_not_expandable():
    out = to_html("> só uma linha")
    assert "<blockquote>" in out and "expandable" not in out
