"""Probe de capacidade de FUNCTION-CALLING NATIVO por provider (slice seguro do tool-calling nativo).

`native_tools: true` num provider diz "TENTE nativo". Mas muitos endpoints "OpenAI-compatible" aceitam o
param `tools=` e devolvem LIXO (ou ignoram e só conversam). Aqui um probe BARATO e CACHEADO confirma que
o endpoint honra function-calling DE VERDADE — manda uma tool trivial com `tool_choice=required` e checa
se voltou um `tool_call`. Se voltar → nativo confiável. Se ignorar/erros → degrada pro JSON-em-texto (o
nosso rail confiável). Fail-safe: qualquer dúvida → JSON. O veredito é o MESMO consultado pelo prompt
(que muda o ramo) e pelo provider (que manda ou não as tools) → nunca há descasamento de modo.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_VERDICT: dict[str, bool] = {}     # pc.name → honra function-calling nativo? (cache por processo)

# Famílias com function-calling SÓLIDO e conhecido (substring no NOME do modelo — NÃO no prefixo de rota
# 'openai/', que cobre também LMStudio/local). Essas pulam o probe (não pagam uma chamada à toa).
_KNOWN_NATIVE = ("gpt", "codex", "claude", "grok", "gemini", "o1", "o3", "o4", "mistral-large", "command-r")


def _is_known_native(model: str) -> bool:
    m = (model or "").lower().rsplit("/", 1)[-1]            # nome do modelo (sem 'openai/' etc.)
    return any(n in m for n in _KNOWN_NATIVE)


def native_supported(pc, *, probe=None) -> bool:
    """O provider honra function-calling NATIVO? False se `native_tools` desligado. Família conhecida
    (gpt/claude/grok/gemini…) → True direto. Senão, roda UM probe (cacheado por provider). `probe`
    injetável p/ teste."""
    if not getattr(pc, "native_tools", False):
        return False
    if _is_known_native(getattr(pc, "model", "")):          # endpoint sólido conhecido → sem probe
        return True
    key = pc.name or pc.model or "?"
    if key in _VERDICT:
        return _VERDICT[key]
    fn = probe or _default_probe
    try:
        ok = bool(fn(pc))
    except Exception as e:  # noqa: BLE001 — probe NUNCA derruba o turno; falhou → degrada (fail-safe)
        logger.warning("probe de native_tools falhou p/ %s (%s) → degradando p/ JSON", key, e)
        ok = False
    _VERDICT[key] = ok
    if not ok:
        logger.info("provider %s não honrou function-calling nativo → usando JSON-em-texto", key)
    return ok


def _default_probe(pc) -> bool:
    """UMA chamada minúscula com uma tool trivial + tool_choice=required → o endpoint devolveu tool_call?
    Best-effort: precisa de rede; qualquer erro propaga p/ o caller, que trata como 'não suporta'."""
    import litellm

    from okami.llm.providers import _kwargs
    tools = [{"type": "function", "function": {
        "name": "ack", "description": "Confirme chamando esta ferramenta.",
        "parameters": {"type": "object", "properties": {}, "required": []}}}]
    msgs = [{"role": "user", "content": "Chame a ferramenta ack agora."}]
    kw = _kwargs(pc, msgs, stream=False)
    kw["tools"] = tools
    kw["tool_choice"] = "required"
    kw["max_tokens"] = 64
    resp = litellm.completion(**kw)
    return bool(getattr(resp.choices[0].message, "tool_calls", None))


def reset_native_cache() -> None:
    """Zera o cache de vereditos (testes / troca de provider em runtime)."""
    _VERDICT.clear()


__all__ = ["native_supported", "reset_native_cache"]
