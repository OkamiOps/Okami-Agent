"""Bug real (reproduzido): send_message cortava o MARKDOWN CRU em pedaços de 4000 chars e só DEPOIS
convertia cada pedaço p/ HTML — as tags <b>/<code>/… inflam o texto, então um pedaço "cabia" no corte
cru e estourava os 4096 do Telegram já renderizado → sendMessage recusava (400) → caía no fallback
plain, perdendo TODA a formatação à toa. Fix: converte a mensagem INTEIRA p/ HTML primeiro, corta o
HTML já pronto depois (_split_html), fechando/reabrindo tag na fronteira do corte."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from okami.channels.markdown_telegram import to_html
from okami.channels.telegram import (
    TelegramClient,
    _split_html,
    _utf16_slice,
    utf16_len,
)


# ----------------------------------------------------------------- (a) split HTML denso, sem estourar 4096
def test_send_message_dense_bold_chunks_fit_4096_utf16_and_keep_formatting(monkeypatch):
    c = TelegramClient("tok")
    sent: list[dict] = []

    def fake_call(method, params, **k):
        sent.append(dict(params))
        return {"ok": True, "result": {"message_id": 1}}

    monkeypatch.setattr(c, "_call", fake_call)
    # markdown denso: cada palavra em negrito → HTML infla MUITO (12 chars de tag por palavra de 6-7 chars)
    text = " ".join(f"**palavra{i}**" for i in range(1200))
    c.send_message("1", text)

    assert len(sent) > 1                                  # precisou partir (senão o teste não testa nada)
    for p in sent:
        assert p.get("parse_mode") == "HTML"
        assert utf16_len(p["text"]) <= 4096                # NUNCA estoura o limite real do Telegram
        # formatação sobrevive: nenhuma parte tem `**` cru vazando (negrito quebrado no corte)
        assert "**" not in p["text"]
        assert "<b>" in p["text"] and "</b>" in p["text"]
        # tags balanceadas dentro de CADA pedaço (senão o Telegram recusaria o parse)
        assert p["text"].count("<b>") == p["text"].count("</b>")


def test_send_message_never_falls_back_to_plain_when_html_fits(monkeypatch):
    # Antes do fix, o pedaço HTML podia passar de 4096 mesmo cabendo em 4000 chars cru → 400 → plain.
    # Com o fix, o corte já é feito no HTML → sendMessage nunca recebe 400 por causa disso.
    c = TelegramClient("tok")
    calls: list[tuple[str, dict]] = []

    def fake_call(method, params, **k):
        calls.append((method, dict(params)))
        if params.get("parse_mode") == "HTML" and utf16_len(params["text"]) > 4096:
            raise urllib.error.HTTPError("url", 400, "bad", {}, None)
        return {"ok": True}

    monkeypatch.setattr(c, "_call", fake_call)
    text = " ".join(f"**palavra{i}**" for i in range(1200))
    c.send_message("1", text)
    assert all(p.get("parse_mode") == "HTML" for _, p in calls)   # nenhuma chamada caiu pro plain


def test_split_html_balances_tags_across_cut():
    rendered = to_html("**" + ("palavra " * 900) + "**")   # negrito gigante renderizado
    parts = _split_html(rendered, 2000)
    assert len(parts) > 1
    for p in parts:
        assert p.count("<b>") == p.count("</b>")
        assert utf16_len(p) <= 2000 + 200                  # folga p/ fechamento de tag na fronteira


def test_split_html_short_text_unchanged():
    assert _split_html("<b>oi</b>", 4096) == ["<b>oi</b>"]


def test_edit_message_converts_full_text_before_cutting(monkeypatch):
    c = TelegramClient("tok")
    cap: dict = {}

    def fake_call(method, params, **k):
        cap.update(method=method, params=dict(params))
        return {"ok": True}

    monkeypatch.setattr(c, "_call", fake_call)
    text = "**" + ("x" * 5000) + "**"                       # negrito bem maior que 4000 chars
    assert c.edit_message("1", 99, text) is True
    assert cap["method"] == "editMessageText"
    assert cap["params"]["parse_mode"] == "HTML"
    assert cap["params"]["text"].count("<b>") == cap["params"]["text"].count("</b>")
    assert utf16_len(cap["params"]["text"]) <= 4096


# ----------------------------------------------------------------- (b) utf16_len com emoji (fora do BMP)
def test_utf16_len_counts_surrogate_pairs():
    assert utf16_len("abc") == 3
    assert utf16_len("😀") == 2                            # fora do BMP → 2 unidades UTF-16
    assert utf16_len("a😀b") == 4
    assert len("a😀b") == 3                                 # len() Python subestima (prova do bug)


def test_utf16_slice_respects_surrogate_pairs():
    s = "😀" * 10                                            # 10 chars Python, 20 unidades UTF-16
    cut = _utf16_slice(s, 5)                                # cabe só 2 emojis inteiros (4 unidades)
    assert utf16_len(cut) <= 5
    assert cut == "😀😀"


# ----------------------------------------------------------------- (c) marcador não-fechado não vaza literal
def test_unclosed_bold_marker_sanitized():
    html = to_html("isso é **negrito que nunca fecha")
    assert "**" not in html
    assert "<b>" not in html                                 # sem par → marcador cai, texto sobrevive puro
    assert "negrito que nunca fecha" in html


def test_unclosed_backtick_sanitized_outside_fence():
    html = to_html("olha o `código que não fecha")
    assert html.count("`") == 0
    assert "código que não fecha" in html


def test_fenced_code_block_not_touched_by_sanitize():
    # a fence ``` protege o conteúdo — backtick ímpar DENTRO do fence não deve mexer no fence em si
    html = to_html("```python\nprint('a`b')\n```")
    assert "<pre>" in html and "</pre>" in html


def test_balanced_bold_survives_sanitize():
    html = to_html("isso é **negrito** normal")
    assert "<b>negrito</b>" in html


# ----------------------------------------------------------------- (d) watchdog de reconexão do polling
def test_get_updates_watchdog_reconnects_after_threshold(monkeypatch, caplog):
    c = TelegramClient("tok")
    reconnects = {"n": 0}

    def fake_opener(*a, **k):
        reconnects["n"] += 1
        return object()

    monkeypatch.setattr(urllib.request, "build_opener", fake_opener)
    monkeypatch.setattr(urllib.request, "install_opener", lambda o: None)

    def always_fails(req, timeout=0):
        # 400 (não-429/5xx) = "_call" já sabe que é erro real e NÃO insiste (sem backoff/sleep real
        # aqui) — deixa o teste rápido e ainda assim exercita o watchdog em get_updates.
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", always_fails)

    # okami/log.py desliga o propagate do logger "okami" (não sobe pro root) — o handler do caplog fica
    # no root, então religa o propagate só durante o teste p/ conseguir capturar o log do watchdog.
    monkeypatch.setattr(logging.getLogger("okami"), "propagate", True)

    import pytest
    with caplog.at_level(logging.ERROR):
        for i in range(1, 5):
            with pytest.raises(Exception):
                c.get_updates()
            assert c._poll_fail_count == i
            assert reconnects["n"] == 0                    # ainda não bateu o threshold
        with pytest.raises(Exception):
            c.get_updates()                                # 5ª falha seguida → dispara o watchdog
    assert reconnects["n"] == 1
    assert c._poll_fail_count == 0                          # contador reseta depois de reconectar
    assert any("falhas seguidas" in r.message for r in caplog.records)


def test_get_updates_resets_fail_count_on_success(monkeypatch):
    c = TelegramClient("tok")
    c._poll_fail_count = 3

    def fake_urlopen(req, timeout=0):
        import io
        return io.BytesIO(json.dumps({"ok": True, "result": []}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c.get_updates()
    assert c._poll_fail_count == 0
