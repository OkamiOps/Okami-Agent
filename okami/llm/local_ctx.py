"""Validação de janela de contexto de backend LOCAL (Ollama), port do que o Hermes faz p/ não truncar calado.

Ollama, por padrão, usa num_ctx pequeno (2048/4096) e TRUNCA o prompt SILENCIOSO quando passa — com o system
prompt grande + tools do Okami isso estoura quase sempre e o modelo "esquece" o início, sem erro nenhum. Aqui
a gente descobre o teto REAL do modelo via /api/show e manda num_ctx no request, p/ o Ollama alocar a janela
certa. Best-effort e fail-open: qualquer erro/timeout → None (segue sem num_ctx, como antes).
"""
from __future__ import annotations

import json
import re
import urllib.request

from okami.llm.native_capability import _is_local

_NUM_CTX_CACHE: dict[tuple[str, str], int | None] = {}   # (api_base, model) -> num_ctx resolvido (ou None)
_MAX_NUM_CTX = 65536                                       # teto sã: não estourar a RAM/VRAM com janela gigante
_NUM_CTX_RE = re.compile(r"num_ctx\s+(\d+)", re.I)


def query_local_num_ctx(api_base: str, model: str, *, timeout: float = 3.0, _opener=None) -> int | None:
    """num_ctx REAL do modelo no Ollama via POST /api/show, ou None (não-Ollama / erro / timeout). Prefere
    `parameters.num_ctx` (config explícita do Modelfile); senão o maior `*.context_length` do model_info."""
    if not api_base or not model:
        return None
    base = api_base.rstrip("/")
    if base.endswith("/v1"):                               # api_base OpenAI-compat → /api/show fica na raiz
        base = base[:-3].rstrip("/")
    try:
        data = json.dumps({"name": model}).encode()
        req = urllib.request.Request(base + "/api/show", data=data,   # noqa: S310 — host local, controlado
                                     headers={"Content-Type": "application/json"})
        opener = _opener or urllib.request.urlopen
        with opener(req, timeout=timeout) as r:             # noqa: S310
            info = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001 — Ollama ausente/erro nunca derruba a chamada; só não seta num_ctx
        return None
    if not isinstance(info, dict):
        return None
    params = info.get("parameters")
    if isinstance(params, str):                             # "num_ctx 8192\nstop ..." (formato do Ollama)
        m = _NUM_CTX_RE.search(params)
        if m:
            v = int(m.group(1))
            if v > 0:
                return v
    mi = info.get("model_info")
    if isinstance(mi, dict):                                # ex.: {"llama.context_length": 8192}
        best = max((v for k, v in mi.items()
                    if k.endswith("context_length") and isinstance(v, int) and v > 0), default=0)
        if best > 0:
            return best
    return None


def resolve_num_ctx(pc, model: str, *, _query=None) -> int | None:
    """num_ctx a usar p/ ESTE provider local (cacheado por api_base+model), clampado a <=_MAX_NUM_CTX. None p/
    backend não-local ou quando não dá p/ descobrir → o request segue sem num_ctx (comportamento antigo)."""
    if not _is_local(pc) or not getattr(pc, "api_base", ""):
        return None
    key = ((pc.api_base or "").rstrip("/"), model or "")
    if key in _NUM_CTX_CACHE:
        return _NUM_CTX_CACHE[key]
    q = _query or query_local_num_ctx
    cap = q(pc.api_base, model)
    val = min(int(cap), _MAX_NUM_CTX) if cap else None
    _NUM_CTX_CACHE[key] = val
    return val


__all__ = ["query_local_num_ctx", "resolve_num_ctx"]
