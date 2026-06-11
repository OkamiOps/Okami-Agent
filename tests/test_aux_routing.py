"""Roteamento de modelo AUXILIAR (porta do auxiliary_client do Hermes, −85% custo de fundo).

Trabalho de FUNDO (destilar skill, review de auto-aprimoramento, moderador de grupo) não
precisa do modelo principal caro. Config:

  auxiliary:
    default: {provider: lmstudio}            # tudo que é fundo vai pro barato
    distill: {provider: lmstudio, model: qwen2.5-7b}
    review:  {provider: lmstudio}

Resolução por TAREFA: auxiliary.<task> → auxiliary.default → (None, None) = modelo principal.
"""
from __future__ import annotations

import json

from okami.config import build_config
from okami.llm.aux import aux_for


def _cfg(aux=None):
    return build_config({"default_provider": "main", "auxiliary": aux or {},
                         "providers": {"main": {"model": "caro", "api_key": "k"},
                                       "cheap": {"model": "barato", "api_key": "k"}}})


def test_no_config_means_main_model():
    assert aux_for(_cfg(), "distill") == (None, None)


def test_task_specific_wins():
    cfg = _cfg({"default": {"provider": "cheap"},
                "distill": {"provider": "cheap", "model": "qwen-7b"}})
    assert aux_for(cfg, "distill") == ("cheap", "qwen-7b")


def test_default_covers_unlisted_tasks():
    cfg = _cfg({"default": {"provider": "cheap"}})
    assert aux_for(cfg, "review") == ("cheap", None)


def test_unknown_provider_falls_back_to_main():
    cfg = _cfg({"distill": {"provider": "inexistente"}})
    assert aux_for(cfg, "distill") == (None, None)     # nunca quebra o fluxo por config errada


def test_distill_uses_aux_provider(tmp_path, monkeypatch):
    from okami import learning
    from okami.core import Step, Task, TaskState
    from okami.llm import providers as prov

    seen = {}

    def fake(cfg, msgs, provider=None, model=None, **kw):
        seen["provider"], seen["model"] = provider, model
        return json.dumps({"worth": False})

    monkeypatch.setattr(prov, "complete_messages", fake)
    t = Task(goal="configurar pipeline de ci no github")
    t.state, t.result = TaskState.COMPLETE, "feito"
    t.steps = [Step(i, tl, {}, "", True) for i, tl in enumerate(
        ["read_file", "write_file", "run_shell", "write_file"])]
    cfg = _cfg({"distill": {"provider": "cheap", "model": "qwen-7b"}})
    learning.distill_skill_llm(cfg, t)
    assert seen["provider"] == "cheap" and seen["model"] == "qwen-7b"
