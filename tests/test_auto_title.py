"""Título automático de sessão (paridade Hermes maybe_auto_title) — okami/gateway/title.py +
AgentEndpoint._maybe_auto_title (okami/gateway/endpoint.py). Cobre: gera na 1ª troca, NUNCA pisa em
título manual (/title), e não atrasa o turno (spawn síncrono de teste = mesma call stack, sem thread
real de produção — o que importa é que _run não BLOQUEIA esperando o resultado do aux_complete)."""
from __future__ import annotations

import tempfile
import types

from okami.channels.base import Channel
from okami.core import Task, TaskState
from okami.gateway import AgentEndpoint
from okami.gateway.title import _clean_title, generate_title


class FakeChannel(Channel):
    name = "fake"
    supports_media = False

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def poll(self):
        return []

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def allowed(self, chat_id):
        return True


def _runner_complete(reply: str = "ok, feito."):
    def _r(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, **kw):
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, reply
        return t
    return _r


def _fake_cfg():
    """cfg mínima com os atributos que _run/_observe/_maybe_compact esperam (persona/auxiliary/
    providers/notifications) — SimpleNamespace() puro faz _observe explodir em self.cfg.persona."""
    return types.SimpleNamespace(persona={}, auxiliary={}, providers={}, notifications=None)


def _ep(runner, cfg=..., channel=None):
    ch = channel or FakeChannel()
    cfg = _fake_cfg() if cfg is ... else cfg   # cfg=None (explícito) desliga o auto-title de propósito
    return AgentEndpoint("dev", cfg=cfg, ws=tempfile.mkdtemp(), channel=ch, run_task=runner,
                         approval_mode="manual", spawn=lambda fn: fn())   # spawn síncrono → determinístico


# ------------------------------------------------------------------ generate_title (unidade pura)
def test_generate_title_strips_quotes_prefix_and_truncates(monkeypatch):
    monkeypatch.setattr("okami.llm.aux.aux_complete",
                        lambda cfg, task, msgs, **kw: '"Título: Configurando o deploy da API"')
    assert generate_title(None, "como configuro o deploy?", "vou te ajudar") == "Configurando o deploy da API"


def test_generate_title_best_effort_on_failure(monkeypatch):
    monkeypatch.setattr("okami.llm.aux.aux_complete",
                        lambda cfg, task, msgs, **kw: (_ for _ in ()).throw(RuntimeError("sem modelo")))
    assert generate_title(None, "oi", "olá") == ""


def test_clean_title_truncates_long_output():
    assert _clean_title("x" * 200) == "x" * 77 + "..."


# ------------------------------------------------------------------ integração via AgentEndpoint
def test_title_generated_after_first_exchange(monkeypatch):
    monkeypatch.setattr("okami.llm.aux.aux_complete",
                        lambda cfg, task, msgs, **kw: "Ajuda com deploy da API")
    ep = _ep(_runner_complete())
    ep.handle("7", "como faço o deploy da minha API?")
    s = ep.session("7")
    assert s.title == "Ajuda com deploy da API"
    assert ep.store.entry("7").get("title") == "Ajuda com deploy da API"


def test_title_not_regenerated_on_second_exchange(monkeypatch):
    calls = []

    def _aux(cfg, task, msgs, **kw):
        calls.append(1)
        return "Primeiro título"
    monkeypatch.setattr("okami.llm.aux.aux_complete", _aux)
    ep = _ep(_runner_complete())
    ep.handle("7", "oi")
    ep.handle("7", "mais uma pergunta")
    assert len(calls) == 1                      # só disparou na 1ª troca
    assert ep.session("7").title == "Primeiro título"


def test_manual_title_never_overwritten_by_auto_title(monkeypatch):
    monkeypatch.setattr("okami.llm.aux.aux_complete",
                        lambda cfg, task, msgs, **kw: "Título automático")
    ep = _ep(_runner_complete())
    ep.handle("7", "/title Nome escolhido por mim")
    ep.handle("7", "primeira pergunta de verdade")
    assert ep.session("7").title == "Nome escolhido por mim"


def test_no_title_when_cfg_is_none(monkeypatch):
    monkeypatch.setattr("okami.llm.aux.aux_complete",
                        lambda cfg, task, msgs, **kw: "não devia rodar")
    ep = _ep(_runner_complete(), cfg=None)
    ep.handle("7", "oi")
    assert ep.session("7").title == ""


def test_empty_title_from_model_does_not_set_session_title(monkeypatch):
    monkeypatch.setattr("okami.llm.aux.aux_complete", lambda cfg, task, msgs, **kw: "")
    ep = _ep(_runner_complete())
    ep.handle("7", "oi")
    assert ep.session("7").title == ""


def test_auto_title_never_blocks_turn_even_if_aux_raises(monkeypatch):
    """Best-effort: uma falha no gerador de título não pode derrubar o turno (a resposta chega normal)."""
    monkeypatch.setattr("okami.llm.aux.aux_complete",
                        lambda cfg, task, msgs, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    ch = FakeChannel()
    ep = _ep(_runner_complete("resposta normal"), channel=ch)
    ep.handle("7", "oi")
    assert any("resposta normal" in t for _, t in ch.sent)
    assert ep.session("7").title == ""
