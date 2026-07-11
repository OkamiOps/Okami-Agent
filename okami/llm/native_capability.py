"""Probe de capacidade de FUNCTION-CALLING NATIVO por provider (slice seguro do tool-calling nativo).

`native_tools: true` num provider diz "TENTE nativo". Mas muitos endpoints "OpenAI-compatible" aceitam o
param `tools=` e devolvem LIXO (ou ignoram e só conversam). Aqui um probe BARATO e CACHEADO confirma que
o endpoint honra function-calling DE VERDADE — manda uma tool trivial com `tool_choice=required` e checa
se voltou um `tool_call`. Se voltar → nativo confiável. Se ignorar/erros → degrada pro JSON-em-texto (o
nosso rail confiável). Fail-safe: qualquer dúvida → JSON. O veredito é o MESMO consultado pelo prompt
(que muda o ramo) e pelo provider (que manda ou não as tools) → nunca há descasamento de modo.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_VERDICT: dict[str, bool] = {}     # pc.name+model → honra function-calling nativo? (cache L1, por processo)


def _verdict_key(pc) -> str:
    """Chave do veredito: provider+model (não só o nome) — o MESMO provider pode trocar de modelo
    (override -m) e o veredito de um modelo não vale p/ outro."""
    return f"{pc.name or '?'}:{pc.model or '?'}"


def _verdict_path():
    """Cache L2 (disco): sobrevive a restart, evita repagar o round-trip do probe a cada boot
    (mirror do padrão de persistência do cred_pool — JSON pequeno, fail-open)."""
    from okami.home import okami_home
    return okami_home() / "native_verdict.json"


def _load_verdicts() -> dict:
    try:
        return json.loads(_verdict_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_verdict(key: str, ok: bool) -> None:
    """Read-modify-write ATÔMICO (lock cross-processo) — best-effort, nunca derruba o turno."""
    try:
        from okami.core.filelock import _FileLock
        p = _verdict_path()
        with _FileLock(p):
            data = _load_verdicts()
            data[key] = bool(ok)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, p)
    except OSError:
        pass

# Famílias com function-calling SÓLIDO e conhecido (substring no NOME do modelo — NÃO no prefixo de rota
# 'openai/', que cobre também LMStudio/local). Essas pulam o probe (não pagam uma chamada à toa).
_KNOWN_NATIVE = ("gpt", "codex", "claude", "grok", "gemini", "o1", "o3", "o4", "mistral-large", "command-r")


def _is_known_native(model: str) -> bool:
    m = (model or "").lower().rsplit("/", 1)[-1]            # nome do modelo (sem 'openai/' etc.)
    return any(n in m for n in _KNOWN_NATIVE)


def _is_local(pc) -> bool:
    """Backend LOCAL (LMStudio/Ollama/llama.cpp…)? tier=local OU api_base apontando p/ a própria máquina."""
    if (getattr(pc, "tier", "") or "").lower() == "local":
        return True
    base = (getattr(pc, "api_base", "") or "").lower()
    return any(h in base for h in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]", "host.docker.internal"))


def native_supported(pc, *, probe=None) -> bool:
    """O provider honra function-calling NATIVO? Política tri-estado (native_tools): False → JSON SEM
    probar; True → nativo SEM probar (hint EXPLÍCITO do catálogo/config — já verificado por quem
    configurou, ex.: provider_catalog.py fixa native_tools=True p/ MiniMax); None (default) → SMART:
    nuvem roda o probe, LOCAL fica em JSON direto. Família conhecida (gpt/claude/grok/gemini…) → True
    direto (sem probe). Veredito cacheado em memória (L1) + disco (L2, cross-restart). `probe` injetável
    p/ teste."""
    nt = getattr(pc, "native_tools", None)
    if nt is not None:                                      # hint EXPLÍCITO (True ou False) → pula o probe
        return bool(nt)
    if _is_local(pc):                                       # default + local → JSON-em-texto (sem probe)
        return False
    if _is_known_native(getattr(pc, "model", "")):          # endpoint sólido conhecido → sem probe
        return True
    key = _verdict_key(pc)
    if key in _VERDICT:
        return _VERDICT[key]
    cached = _load_verdicts().get(key)                      # L2: sobrevive a restart, sem pagar round-trip
    if cached is not None:
        _VERDICT[key] = bool(cached)
        return _VERDICT[key]
    fn = probe or _default_probe
    try:
        ok = bool(fn(pc))
    except Exception as e:  # noqa: BLE001 — probe NUNCA derruba o turno; falhou → degrada (fail-safe)
        logger.warning("probe de native_tools falhou p/ %s (%s) → degradando p/ JSON", key, e)
        ok = False
    _VERDICT[key] = ok
    _save_verdict(key, ok)
    if not ok:
        logger.info("provider %s não honrou function-calling nativo → usando JSON-em-texto", key)
    return ok


def _default_probe(pc) -> bool:
    """UMA chamada minúscula com uma tool trivial + tool_choice=required → o endpoint devolveu tool_call?
    Best-effort: precisa de rede; qualquer erro propaga p/ o caller, que trata como 'não suporta'."""
    from okami.llm.transport_registry import CompletionRequest, default_transport_registry
    from okami.llm.target_resolver import TargetResolver
    tools = [{"type": "function", "function": {
        "name": "ack", "description": "Confirme chamando esta ferramenta.",
        "parameters": {"type": "object", "properties": {}, "required": []}}}]
    msgs = [{"role": "user", "content": "Chame a ferramenta ack agora."}]
    request = CompletionRequest(
        messages=msgs,
        overrides={"tools": tools, "tool_choice": "required", "max_tokens": 64},
    )
    target = TargetResolver().resolve_provider(pc)
    resp = default_transport_registry().complete(target, pc, request)
    return bool(getattr(resp, "tool_calls", None))


def reset_native_cache() -> None:
    """Zera o cache de vereditos — L1 (memória) E L2 (disco): testes / troca de provider em runtime
    (ex.: `/native-tools`) não podem ficar reféns de um veredito velho persistido de sessão anterior."""
    _VERDICT.clear()
    try:
        p = _verdict_path()
        if p.exists():
            p.unlink()
    except OSError:
        pass


__all__ = ["native_supported", "reset_native_cache"]
