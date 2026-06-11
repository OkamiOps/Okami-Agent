"""Markdown → HTML do Telegram (paridade Hermes): o agente escreve **negrito**/`código` e o usuário
via os ASTERISCOS literais — o sendMessage não mandava parse_mode. Agora converte p/ HTML do Telegram
com FALLBACK p/ texto puro se a API recusar o parse (nunca perde a mensagem)."""

from __future__ import annotations

import io
import json
import urllib.error

from okami.channels.markdown_telegram import to_html
from okami.channels.telegram import TelegramClient


# ----------------------------------------------------------------- conversão (pura)
def test_bold_italic_strike():
    assert to_html("**forte** e *leve* e ~~riscado~~") == "<b>forte</b> e <i>leve</i> e <s>riscado</s>"


def test_underscore_italic():
    assert to_html("um _itálico_ aqui") == "um <i>itálico</i> aqui"
    assert to_html("snake_case_nome fica intacto") == "snake_case_nome fica intacto"


def test_inline_code_escapes_html():
    assert to_html("use `a < b && c`") == "use <code>a &lt; b &amp;&amp; c</code>"


def test_fenced_code_block_with_language():
    out = to_html("```python\nprint('<oi>')\n```")
    assert out == '<pre><code class="language-python">print(\'&lt;oi&gt;\')</code></pre>'


def test_fenced_code_protects_markdown_inside():
    out = to_html("```\n**nao é negrito**\n```")
    assert "<b>" not in out and "**nao é negrito**" in out


def test_headers_become_bold():
    assert to_html("## Resumo\ntexto") == "<b>Resumo</b>\ntexto"


def test_links():
    assert to_html("[site](https://x.com/a?b=1)") == '<a href="https://x.com/a?b=1">site</a>'


def test_plain_html_chars_escaped():
    assert to_html("2 < 3 & 4 > 1") == "2 &lt; 3 &amp; 4 &gt; 1"


def test_plain_text_unchanged():
    assert to_html("oi, tudo bem?") == "oi, tudo bem?"


def test_bullet_list_kept():
    assert to_html("- item um\n- item dois") == "- item um\n- item dois"


# ----------------------------------------------------------------- envio com parse_mode + fallback
def test_send_message_uses_html_parse_mode(monkeypatch):
    c = TelegramClient("tok")
    calls: list[dict] = []
    monkeypatch.setattr(c, "_call", lambda m, p, **k: (calls.append(dict(p)), {"ok": True})[1])
    c.send_message("1", "**oi** `x`")
    assert calls[0]["parse_mode"] == "HTML"
    assert calls[0]["text"] == "<b>oi</b> <code>x</code>"


def test_send_message_falls_back_to_plain_on_parse_error(monkeypatch):
    c = TelegramClient("tok")
    calls: list[dict] = []

    def fake(method, p, **k):
        calls.append(dict(p))
        if p.get("parse_mode"):                            # HTML recusado pela API → 400
            raise urllib.error.HTTPError("u", 400, "can't parse entities", {},
                                         io.BytesIO(json.dumps({}).encode()))
        return {"ok": True}

    monkeypatch.setattr(c, "_call", fake)
    c.send_message("1", "**negrito** com tag <oi> estranha")
    assert len(calls) == 2
    assert "parse_mode" not in calls[1]
    assert calls[1]["text"] == "**negrito** com tag <oi> estranha"   # cru, nada perdido


def test_send_message_plain_text_skips_parse_mode(monkeypatch):
    c = TelegramClient("tok")
    calls: list[dict] = []
    monkeypatch.setattr(c, "_call", lambda m, p, **k: (calls.append(dict(p)), {"ok": True})[1])
    c.send_message("1", "sem markdown nenhum")
    assert "parse_mode" not in calls[0]                    # texto puro → não paga conversão/risco de parse


def test_send_message_split_still_respects_limit(monkeypatch):
    c = TelegramClient("tok")
    sent: list[str] = []
    monkeypatch.setattr(c, "_call", lambda m, p, **k: (sent.append(p["text"]), {"ok": True})[1])
    c.send_message("1", "y" * 9000)
    assert len(sent) >= 3 and all(len(s) <= 4000 for s in sent)
