"""Janelas de uso de ASSINATURA (pesquisa #6 item 14, paridade Hermes account_usage).

"Quanto sobrou do meu plano de 5h" — a pergunta-chave de um agente subscription-only. Consulta o
endpoint de usage da assinatura (Codex/ChatGPT: rate_limit.primary/secondary; Anthropic OAuth:
five_hour/seven_day). Fail-open: sem token / erro de rede → lista vazia, nunca quebra.
"""
from __future__ import annotations

from okami.llm import account_usage as au


def test_parse_codex_windows():
    payload = {"plan_type": "plus", "rate_limit": {
        "primary_window": {"used_percent": 42.5, "reset_at": 1000},
        "secondary_window": {"used_percent": 80.0, "reset_at": 5000}}}
    wins = au.fetch_codex_usage(token="tok", account_id="acc", http=lambda url, headers: payload)
    assert len(wins) == 2
    assert wins[0].label.lower().startswith("sess") and wins[0].used_percent == 42.5
    assert wins[1].used_percent == 80.0


def test_codex_no_token_returns_empty(monkeypatch):
    # sem token no store → vazio (sem chamada de rede). Mocka a resolução p/ não depender da máquina.
    monkeypatch.setattr("okami.llm.oauth.codex_access_token", lambda: None)
    assert au.fetch_codex_usage(token=None) == []


def test_codex_fail_open_on_http_error():
    def boom(url, headers):
        raise RuntimeError("rede caiu")
    assert au.fetch_codex_usage(token="t", http=boom) == []


def test_codex_skips_window_without_percent():
    payload = {"rate_limit": {"primary_window": {"reset_at": 1}, "secondary_window": {"used_percent": 10}}}
    wins = au.fetch_codex_usage(token="t", http=lambda u, h: payload)
    assert len(wins) == 1 and wins[0].used_percent == 10


def test_codex_url_resolution():
    assert au._codex_usage_url("https://chatgpt.com/backend-api/codex").endswith("/wham/usage")
    assert au._codex_usage_url("https://example.com/api").endswith("/api/codex/usage")


def test_render_lines_show_percent_and_remaining():
    wins = [au.UsageWindow("Sessão (5h)", 42.0, resets_at=3600 * 2),
            au.UsageWindow("Semana", 90.0, resets_at=None)]
    lines = au.render_usage_lines(wins, now=lambda: 0.0)
    assert any("42%" in x and "Sessão" in x for x in lines)
    assert any("58%" in x or "restante" in x.lower() for x in lines)   # mostra o que SOBRA
    assert any("2h" in x for x in lines)                               # reseta em ~2h
    assert any("90%" in x for x in lines)


def test_account_usage_aggregates_fail_open(monkeypatch):
    monkeypatch.setattr(au, "fetch_codex_usage", lambda **kw: [au.UsageWindow("Sessão", 10.0)])
    monkeypatch.setattr(au, "fetch_anthropic_usage", lambda **kw: (_ for _ in ()).throw(RuntimeError("x")))
    wins = au.account_usage(None)
    assert len(wins) == 1                              # codex ok, anthropic falhou → não quebra


def test_high_utilization_flagged():
    lines = au.render_usage_lines([au.UsageWindow("Sessão", 95.0)], now=lambda: 0.0)
    assert any("⚠" in x or "95%" in x for x in lines)
