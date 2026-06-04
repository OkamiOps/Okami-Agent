"""Descoberta de modelos por provider (§3.5).

Híbrido (igual Hermes + OpenClaw):
  - **ao vivo**: `GET {api_base}/models` (OpenAI-compat) → modelos REAIS do servidor (Hermes #7103).
    É o caso do LMStudio/Ollama/proxy/OpenAI/OpenRouter/etc — pega o que está de fato disponível.
  - **catálogo**: assinaturas/OAuth sem `/models` (Codex, Claude) usam a lista embarcada do preset
    (estilo OpenClaw provider plugin catalog).
Nunca quebra: falhou a busca → cai pro catálogo → vazio → o chamador pede o id no texto.
"""

from __future__ import annotations

import json
import urllib.request

# ids que não são modelos de chat (não oferecer no menu).
_SKIP = ("embedding", "embed", "whisper", "tts", "dall-e", "dalle", "moderation",
         "rerank", "image", "audio", "speech", "guard")


def _http_models(api_base: str, key: str | None = None, timeout: float = 8.0) -> list[str]:
    url = api_base.rstrip("/") + "/models"
    req = urllib.request.Request(url)
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        data = json.loads(r.read().decode("utf-8"))
    items = data.get("data") if isinstance(data, dict) else data
    ids = []
    for m in (items or []):
        mid = m.get("id") if isinstance(m, dict) else str(m)
        if mid:
            ids.append(str(mid))
    return ids


def discover_models(*, api_base: str | None = None, key: str | None = None,
                    transport: str = "litellm", catalog: list[str] | None = None,
                    timeout: float = 8.0) -> tuple[list[str], str]:
    """Devolve (modelos, fonte) — fonte ∈ {'live','catalog','none'}.

    OpenAI-compat (api_base + transport litellm) → busca ao vivo, filtra não-chat.
    Senão usa o catálogo do preset. Tolerante a falha de rede."""
    catalog = list(catalog or [])
    tried = False
    if api_base and transport in ("litellm", "", None):
        tried = True
        try:
            ids = [i for i in _http_models(api_base, key, timeout)
                   if not any(s in i.lower() for s in _SKIP)]
            if ids:
                return sorted(set(ids)), "live"
        except Exception:  # noqa: BLE001 — offline/401 → cai pro catálogo
            pass
    if catalog:
        return catalog, "catalog"
    if api_base and not tried:                    # só se NÃO tentou (ex.: oauth com /models autenticado)
        try:
            ids = _http_models(api_base, key, timeout)
            if ids:
                return sorted(set(ids)), "live"
        except Exception:  # noqa: BLE001
            pass
    return [], "none"
