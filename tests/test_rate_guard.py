"""Guarda de rate-limit CROSS-SESSÃO (porta do nous_rate_guard do Hermes).

Dor real do Marcos: "overloaded por 2 vezes". O gateway, o cron e o CLI rodam em processos
separados — um 429/529 num deles não impedia os outros de martelar o mesmo provider (cada
turno re-tentava 3×, amplificando o buraco). Agora o primeiro 429 grava o reset em
~/.okami/rate_limits/<provider>.json e TODA sessão checa o arquivo antes de chamar.
"""
from __future__ import annotations

import json
import time

from okami.llm import rate_guard as rg


def test_no_file_means_clear(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    assert rg.blocked_for("anthropic") == 0.0


def test_note_and_block(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    rg.note_rate_limited("anthropic", ttl=120)
    left = rg.blocked_for("anthropic")
    assert 100 < left <= 120
    assert rg.blocked_for("openai") == 0.0           # outro provider não é afetado


def test_expired_means_clear(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    f = tmp_path / "rate_limits" / "anthropic.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"until": time.time() - 5}))
    assert rg.blocked_for("anthropic") == 0.0


def test_retry_after_wins_over_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    rg.note_rate_limited("nous", ttl=3600, retry_after=30)
    assert rg.blocked_for("nous") <= 30              # provider sabe melhor que o default


def test_overloaded_uses_short_ttl(tmp_path, monkeypatch):
    # 503/529 é transitório (segundos/minutos) — não pode parquear por 1h como o 429
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    rg.note_overloaded("anthropic")
    left = rg.blocked_for("anthropic")
    assert 0 < left <= 60


def test_429_without_retry_after_is_transient_not_1h(tmp_path, monkeypatch):
    # bug #9: 429 SEM retry-after num provider multiplexado (OpenRouter/Nous) NÃO pode travar o
    # provider INTEIRO por 1h cross-sessão — trata como transitório (pausa curta anti-stampede).
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    rg.note_rate_limited("openrouter")               # sem retry_after, sem ttl explícito, sem genuine
    left = rg.blocked_for("openrouter")
    assert 0 < left <= 60                             # curto, NÃO ~3600


def test_429_genuine_blocks_long(tmp_path, monkeypatch):
    # quando o caller SABE que é a quota da conta que esgotou → bloqueio longo (1h) é correto.
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    rg.note_rate_limited("codex", genuine=True)
    assert rg.blocked_for("codex") > 600


def test_corrupt_file_fails_open(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    f = tmp_path / "rate_limits" / "x.json"
    f.parent.mkdir(parents=True)
    f.write_text("{lixo")
    assert rg.blocked_for("x") == 0.0                # guarda nunca pode travar o agente


def test_clear(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    rg.note_rate_limited("anthropic", ttl=120)
    rg.clear("anthropic")
    assert rg.blocked_for("anthropic") == 0.0


# ── integração com o loop de retry (complete_messages_ex) ───────────────────

def _cfg2():
    from okami.config import build_config
    return build_config({"default_provider": "a", "providers": {
        "a": {"model": "ma", "api_keys": ["k1", "k2", "k3"], "fallback": ["b"]},
        "b": {"model": "mb", "api_key": "kb"}}})


def test_429_notes_guard_and_blocked_provider_probes_once(tmp_path, monkeypatch):
    from okami.llm import providers as prov
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    calls = []

    def fake(pc, messages, model, schema, overrides):
        calls.append(pc.name)
        if pc.name == "a":
            raise RuntimeError("429 too many requests")
        return "ok-b"

    monkeypatch.setattr(prov, "_complete_one", fake)
    out = prov.complete_messages(_cfg2(), [{"role": "user", "content": "x"}], _sleep=lambda s: None)
    assert out == "ok-b"
    assert rg.blocked_for("a") > 0                    # 429 gravou a marca cross-sessão

    # 2ª sessão (mesmo processo aqui, mas a marca é via ARQUIVO): 'a' bloqueado → UMA sonda só,
    # sem rodar as 3 chaves — era a amplificação que detonava a quota
    calls.clear()
    out = prov.complete_messages(_cfg2(), [{"role": "user", "content": "y"}], _sleep=lambda s: None)
    assert out == "ok-b"
    assert calls.count("a") == 1


def test_overloaded_notes_short_guard(tmp_path, monkeypatch):
    from okami.llm import providers as prov
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)

    def fake(pc, messages, model, schema, overrides):
        if pc.name == "a":
            raise RuntimeError("overloaded_error 529")
        return "ok-b"

    monkeypatch.setattr(prov, "_complete_one", fake)
    prov.complete_messages(_cfg2(), [{"role": "user", "content": "x"}], _sleep=lambda s: None)
    assert 0 < rg.blocked_for("a") <= 60


def test_success_clears_guard(tmp_path, monkeypatch):
    from okami.llm import providers as prov
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    rg.note_overloaded("a", ttl=60)
    monkeypatch.setattr(prov, "_complete_one", lambda pc, m, mo, s, o: "ok-a")
    out = prov.complete_messages(_cfg2(), [{"role": "user", "content": "x"}], _sleep=lambda s: None)
    assert out == "ok-a"
    assert rg.blocked_for("a") == 0.0                 # voltou a funcionar → limpa a marca


# ── retry_after: o provider sabe melhor que o TTL default ───────────────────

def test_classify_extracts_retry_after_from_message():
    from okami.llm.errors import classify
    ce = classify(RuntimeError("429 rate limit exceeded. Please retry after 30 seconds"))
    assert ce.reason == "rate_limit" and ce.retry_after == 30.0
    ce2 = classify(RuntimeError("Rate limit. Try again in 2.5s"))
    assert ce2.retry_after == 2.5
    ce3 = classify(RuntimeError("429 too many requests"))
    assert ce3.retry_after is None                     # sem dica → TTL default da guarda


def test_classify_extracts_retry_after_attr():
    from okami.llm.errors import classify

    class E(Exception):
        retry_after = 17

    assert classify(E("429")).retry_after == 17.0


def test_guard_honors_provider_retry_after(tmp_path, monkeypatch):
    from okami.llm import providers as prov
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)

    def fake(pc, messages, model, schema, overrides):
        if pc.name == "a":
            raise RuntimeError("429 rate limited; retry after 20 seconds")
        return "ok-b"

    monkeypatch.setattr(prov, "_complete_one", fake)
    prov.complete_messages(_cfg2(), [{"role": "user", "content": "x"}], _sleep=lambda s: None)
    assert rg.blocked_for("a") <= 20                   # 20s do provider, não 1h do default
