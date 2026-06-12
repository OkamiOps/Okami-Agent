"""Roteamento auxiliar COMPLETO p/ trabalho de fundo (pesquisa #5 item 57).

review e distill já roteavam. Aqui: aux_complete() (helper único) + compressão de conversa do
gateway (task "compress") e moderador de grupo (task "moderator") no modelo barato. Fail-open:
sem config auxiliar → modelo principal (provider=None).
"""
from __future__ import annotations

from okami.config import build_config
from okami.llm import providers as prov
from okami.llm.aux import aux_complete, aux_for


def _cfg(aux=None):
    return build_config({"default_provider": "main", "auxiliary": aux or {},
                         "providers": {"main": {"model": "caro", "api_key": "k"},
                                       "cheap": {"model": "barato", "api_key": "k"}}})


def test_aux_complete_routes_task_to_cheap_model(monkeypatch):
    seen = {}

    def fake(cfg, messages, *, provider=None, model=None, **kw):
        seen.update(provider=provider, model=model)
        return "resumo"

    monkeypatch.setattr(prov, "complete_messages", fake)
    cfg = _cfg({"compress": {"provider": "cheap", "model": "qwen-7b"}})
    out = aux_complete(cfg, "compress", [{"role": "user", "content": "x"}])
    assert out == "resumo"
    assert seen["provider"] == "cheap" and seen["model"] == "qwen-7b"


def test_aux_complete_fail_open_to_main(monkeypatch):
    seen = {}

    def fake(cfg, messages, *, provider=None, model=None, **kw):
        seen.update(provider=provider, model=model)
        return "ok"

    monkeypatch.setattr(prov, "complete_messages", fake)
    assert aux_complete(_cfg(), "compress", [{"role": "user", "content": "x"}]) == "ok"
    assert seen["provider"] is None and seen["model"] is None


def test_moderator_task_resolves():
    cfg = _cfg({"default": {"provider": "cheap"}})
    assert aux_for(cfg, "moderator") == ("cheap", None)


def test_llm_moderator_uses_aux_model(monkeypatch):
    from okami.agents.group import Member, llm_moderator
    seen = {}

    def fake(cfg, messages, *, provider=None, model=None, **kw):
        seen.update(provider=provider, model=model)
        return '{"speaker": "dev"}'

    monkeypatch.setattr(prov, "complete_messages", fake)
    cfg = _cfg({"moderator": {"provider": "cheap"}})
    sel = llm_moderator(cfg)
    m = Member(id="dev", role="developer")
    assert sel([("user", "quem implementa?")], [m], set()) == "dev"
    assert seen["provider"] == "cheap"
