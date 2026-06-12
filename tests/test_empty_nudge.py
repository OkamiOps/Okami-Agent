"""Escada de RESPOSTA VAZIA — nível "nudge" (pesquisa #5 item 7, Hermes empty-response ladder).

Antes de queimar chave/backoff/failover, UMA re-tentativa com um empurrão ("sua resposta veio
vazia; responda agora") fundido na última mensagem user — numa CÓPIA local. O scaffolding
sintético NUNCA entra no histórico durável (a lista do chamador fica intocada), e o nudge não
consome tentativa do pool.
"""
from __future__ import annotations

from okami.config import build_config
from okami.llm import providers as prov
from okami.llm.usage import Completion


def _cfg():
    return build_config({"default_provider": "a", "providers": {"a": {"model": "ma"}}})


def test_empty_nudges_once_then_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    calls = []

    def fake_one(pc, messages, model, schema, overrides):
        calls.append([dict(m) for m in messages])
        if len(calls) == 1:
            return Completion(text="")                       # 1ª: vazia
        return Completion(text="agora sim", provider=pc.name)

    monkeypatch.setattr(prov, "_complete_one", fake_one)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "fala"}]
    res = prov.complete_messages_ex(_cfg(), msgs, _sleep=lambda s: None)
    assert res.text == "agora sim"
    assert len(calls) == 2
    assert "VAZIA" in calls[1][-1]["content"]                # 2ª chamada levou o nudge
    assert calls[1][-1]["role"] == "user"                    # fundido na user (alternância preservada)


def test_durable_history_untouched_by_nudge(monkeypatch, tmp_path):
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    seq = iter([Completion(text=""), Completion(text="ok")])
    monkeypatch.setattr(prov, "_complete_one", lambda pc, m, model, s, ov: next(seq))
    msgs = [{"role": "user", "content": "fala"}]
    prov.complete_messages_ex(_cfg(), msgs, _sleep=lambda s: None)
    assert msgs == [{"role": "user", "content": "fala"}]     # scaffolding NÃO vazou pro durável


def test_nudge_does_not_consume_pool_attempt(monkeypatch, tmp_path):
    # pool de 2 chaves: vazio+nudge (mesma chave) → vazio de novo → ainda sobram as 2 tentativas reais
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    prov._key_cooldown.clear()
    cfg = build_config({"default_provider": "a",
                        "providers": {"a": {"model": "ma", "api_keys": ["k1", "k2"]}}})
    calls = []

    def fake_one(pc, messages, model, schema, overrides):
        calls.append(overrides.get("_api_key"))
        if len(calls) <= 2:
            return Completion(text="")                       # vazia na 1ª e no nudge
        return Completion(text="ok")

    monkeypatch.setattr(prov, "_complete_one", fake_one)
    res = prov.complete_messages_ex(cfg, [{"role": "user", "content": "x"}], _sleep=lambda s: None)
    assert res.text == "ok"
    # sem o nudge-extra, o pool de 2 morreria na 2ª chamada; a 3ª provar que o nudge não consumiu tentativa
    assert len(calls) == 3


def test_fallback_provider_gets_clean_messages(monkeypatch, tmp_path):
    # se mesmo com nudge continuar vazio e rolar failover, o provider B recebe as mensagens ORIGINAIS
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    cfg = build_config({"default_provider": "a", "providers": {
        "a": {"model": "ma", "fallback": ["b"]}, "b": {"model": "mb"}}})
    seen_b = []

    def fake_one(pc, messages, model, schema, overrides):
        if pc.name == "a":
            return Completion(text="")
        seen_b.append([dict(m) for m in messages])
        return Completion(text="ok-b", provider="b")

    monkeypatch.setattr(prov, "_complete_one", fake_one)
    res = prov.complete_messages_ex(cfg, [{"role": "user", "content": "fala"}], _sleep=lambda s: None)
    assert res.text == "ok-b"
    assert "VAZIA" not in seen_b[0][-1]["content"]           # B começou limpo, sem o scaffolding do A
