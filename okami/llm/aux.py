"""Roteamento de modelo AUXILIAR p/ trabalho de FUNDO (porta do auxiliary_client do Hermes).

Destilar skill, review de auto-aprimoramento, moderar grupo, julgar aprovação: nada disso
precisa do modelo principal (caro/limitado por assinatura). O Hermes mede −85% de custo de
fundo roteando essas tarefas p/ um modelo barato. Config (okami.yaml):

  auxiliary:
    default: {provider: lmstudio}                  # fallback p/ toda tarefa de fundo
    distill: {provider: lmstudio, model: qwen-7b}  # por tarefa: distill | review | compress | moderator | approval

Resolução: auxiliary.<task> → auxiliary.default → (None, None) = segue no modelo principal.
Config errada (provider inexistente) NUNCA quebra o fluxo — só cai no principal.
"""
from __future__ import annotations


def aux_for(cfg, task: str) -> tuple[str | None, str | None]:
    """(provider, model) do modelo auxiliar p/ a `task`, ou (None, None) = modelo principal."""
    aux = getattr(cfg, "auxiliary", None) or {}
    entry = aux.get(task) or aux.get("default") or {}
    provider = entry.get("provider")
    if provider and provider not in (getattr(cfg, "providers", None) or {}):
        return None, None                       # provider inexistente → fail-open pro principal
    model = entry.get("model")
    return (provider or None), (model or None)


def aux_complete(cfg, task: str, messages: list[dict], **kw) -> str:
    """Chamada de FUNDO já roteada: resolve o auxiliar da `task` e completa. É o helper único p/
    compress (resumo de conversa), moderator (grupo), etc. — fail-open pro modelo principal."""
    from okami.llm import providers as prov
    provider, model = aux_for(cfg, task)
    return prov.complete_messages(cfg, messages, provider=provider, model=model, **kw)
