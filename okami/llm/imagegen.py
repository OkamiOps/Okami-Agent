"""Geração de imagem (§13) — gpt-image-2 via ASSINATURA do Codex/ChatGPT (token OAuth nativo).

DOIS FLUXOS (pedido do usuário), no MESMO endpoint (não são rotas separadas):
- **sem referência**: texto → imagem nova.
- **com referência**: o agente MANDA a(s) imagem(ns) recebida(s) (como `input_image` no `input` da
  Responses API) + o prompt p/ o gpt-image-2 (ex.: "vire um infográfico"). O agente NÃO edita o
  arquivo — quem gera é o modelo.

MECANISMO (corrigido — a versão anterior batia em `api.openai.com/v1/images/*`, a REST Images API
clássica, que um token OAuth de assinatura ChatGPT/Codex NÃO consegue autenticar — 401):
POST `https://chatgpt.com/backend-api/codex/responses` (mesmo host do transport de chat, ver
`okami/llm/transports.py:CODEX_URL`) com um corpo Responses API carregando
`tools:[{"type":"image_generation","model":"gpt-image-2",...}]` +
`tool_choice:{"type":"allowed_tools","mode":"required","tools":[{"type":"image_generation"}]}`,
`stream:true`, `store:false`. A imagem volta em base64 dentro dos eventos SSE
(`image_generation_call.result` / `partial_image_b64`) — decodifica e grava no `out`.

Precisa dos MESMOS headers anti-Cloudflare que o transport de chat (VPS sem originator de primeira
parte leva 403 `cf-mitigated:challenge` mesmo com token válido) — ver `okami/llm/codex_headers.py`.

FALLBACK: se o Codex não estiver logado OU a chamada falhar (403/401/rede), tenta um provider
configurado em `media.image` (registry `IMAGE_BACKENDS`, mesmo padrão do `videogen.py`). Sem Codex
E sem fallback → erro claro (o `check()` da tool cuida de podar do registro nesse caso).
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_MODEL = "gpt-image-2"       # modelo da tool image_generation (o que de fato gera a imagem)
DEFAULT_CHAT_MODEL = "gpt-5.5"      # host da Responses API que INVOCA a tool (não gera a imagem ele mesmo).
                                    # DEVE ser modelo aceito pela assinatura codex — gpt-5.1 dá HTTP 400
                                    # "model not supported"; gpt-5.5 é o mesmo host do provider codex (okami.yaml).
                                    # Verificado ao vivo 2026-07-08: gera PNG real via assinatura.
DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "medium"
_TIMEOUT = 300.0

_INSTRUCTIONS = ("You are an assistant that must fulfill image generation and image editing requests "
                 "by using the image_generation tool when provided.")


# --------------------------------------------------------------------- codex (fluxo principal)
def _codex_token_or_none() -> str | None:
    from okami.llm import oauth
    return oauth.codex_access_token()


def _input_image_part(path: str) -> dict:
    """Converte uma imagem local em `input_image` (data URL base64) p/ o `input` da Responses API."""
    p = Path(path)
    raw = p.read_bytes()
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    b64 = base64.b64encode(raw).decode("ascii")
    return {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"}


def _build_payload(prompt: str, references: list | None, model: str, size: str, quality: str,
                    chat_model: str) -> dict:
    """Corpo da Responses API p/ uma chamada de `image_generation`. text→image (sem `references`) e
    image→image (com `references`) usam o MESMO corpo — a diferença é só as `input_image` parts."""
    content: list[dict] = [{"type": "input_text", "text": prompt}]
    for ref in references or []:
        content.append(_input_image_part(ref))
    return {
        "model": chat_model,
        "store": False,        # exigido pelo endpoint (mesmo do transport de chat)
        "stream": True,        # idem — só SSE
        "instructions": _INSTRUCTIONS,
        "input": [{"type": "message", "role": "user", "content": content}],
        "tools": [{"type": "image_generation", "model": model, "size": size, "quality": quality,
                  "output_format": "png", "background": "opaque", "partial_images": 1}],
        "tool_choice": {"type": "allowed_tools", "mode": "required", "tools": [{"type": "image_generation"}]},
    }


def _extract_image_b64(obj) -> str | None:
    """Vasculha um evento SSE (dict/list aninhado) atrás do base64 da imagem — cobre tanto o item
    terminal `image_generation_call` (campo `result`) quanto os eventos de progresso
    (`partial_image_b64`)."""
    found = None
    if isinstance(obj, dict):
        if obj.get("type") == "image_generation_call":
            result = obj.get("result")
            if isinstance(result, str) and result:
                found = result
        partial = obj.get("partial_image_b64")
        if isinstance(partial, str) and partial:
            found = partial
        for v in obj.values():
            nested = _extract_image_b64(v)
            if nested:
                found = nested
    elif isinstance(obj, list):
        for v in obj:
            nested = _extract_image_b64(v)
            if nested:
                found = nested
    return found


def _parse_sse_image(lines) -> str:
    """Percorre o SSE da Responses API → devolve o ÚLTIMO base64 visto (partial_images chega em ordem
    crescente de completude; o evento terminal substitui os parciais). Erro do servidor (`response.failed`
    /`error`) → RuntimeError com o detalhe (não falha silenciosa)."""
    image_b64: str | None = None
    for raw in lines:
        line = raw.decode("utf-8", "ignore") if isinstance(raw, (bytes, bytearray)) else raw
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        t = obj.get("type", "")
        if t == "response.failed" or t == "error":
            err = (obj.get("response") or {}).get("error") or obj.get("error") or obj
            raise RuntimeError(f"geração de imagem falhou: {str(err)[:300]}")
        found = _extract_image_b64(obj)
        if found:
            image_b64 = found
    if not image_b64:
        raise RuntimeError("resposta do codex sem imagem (stream sem image_generation_call.result)")
    return image_b64


def _default_send(url: str, payload: dict, headers: dict, timeout: float):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return list(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError(f"codex image HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"codex image: endpoint inacessível: {e}") from e


def _generate_codex(prompt: str, out_path: Path, references: list | None, model: str, size: str,
                    quality: str, chat_model: str, token: str, timeout: float, *, _send=None) -> str:
    from okami.llm import oauth
    from okami.llm.codex_headers import cloudflare_headers
    from okami.llm.transports import CODEX_URL
    account = oauth.codex_account_id()
    payload = _build_payload(prompt, references, model, size, quality, chat_model)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
              "Accept": "text/event-stream"}
    headers.update(cloudflare_headers(token, account))   # anti-403 Cloudflare (VPS) — ver codex_headers.py
    send = _send or _default_send
    lines = send(CODEX_URL, payload, headers, timeout)
    image_b64 = _parse_sse_image(lines)
    out_path.write_bytes(base64.b64decode(image_b64))
    return str(out_path)


# --------------------------------------------------------------------- fallback (media.image)
# Registry de backends nomeados (paridade com VIDEO_BACKENDS em videogen.py) — presets de
# URL/model p/ o dono escolher `media.image.backend: flux` em vez de digitar a url à mão.
IMAGE_BACKENDS: dict[str, dict] = {
    "flux": {"url": "https://fal.run/fal-ai/flux/dev", "model": "flux-dev"},
    "flux-pro": {"url": "https://fal.run/fal-ai/flux-pro/v1.1", "model": "flux-pro-1.1"},
    "openrouter": {"url": "https://openrouter.ai/api/v1/images/generations", "model": "openai/gpt-image-1"},
}


def image_backends() -> list[dict]:
    """Lista os backends nomeados disponíveis (p/ `okami image --list` e descoberta)."""
    return [{"name": k, **v} for k, v in IMAGE_BACKENDS.items()]


def image_config(cfg) -> dict | None:
    """Resolve `media.image`. Aceita um BACKEND nomeado (`backend: flux`) OU url direta. None se não
    configurado (sem backend válido nem url) — mesmo contrato de `videogen.video_config`."""
    if cfg is None:
        return None
    media = (getattr(cfg, "media", None) or {}) if not isinstance(cfg, dict) else (cfg.get("media") or {})
    v = media.get("image") or {}
    backend = (v.get("backend") or "").strip().lower()
    if backend:                                            # preset nomeado
        preset = IMAGE_BACKENDS.get(backend)
        if preset is None:
            return None                                    # backend desconhecido → não configurado
        return {"url": v.get("url") or preset["url"], "model": v.get("model") or preset["model"],
                "api_key_env": v.get("api_key_env", ""), "backend": backend}
    if not v.get("url"):
        return None
    return {"url": v["url"], "model": v.get("model", ""), "api_key_env": v.get("api_key_env", ""), "backend": ""}


def _resolve_cfg(cfg):
    if cfg is not None:
        return cfg
    try:
        from okami.config import load_config
        return load_config()
    except Exception:  # noqa: BLE001 — sem config carregável → sem fallback (não quebra o caminho codex)
        return None


def _default_fallback_post(url: str, body: dict, headers: dict):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)  # noqa: S310 — URL do config do dono
    try:
        with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"fallback de imagem HTTP {e.code}: "
                           f"{e.read().decode('utf-8', 'ignore')[:300]}") from e
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"endpoint de imagem inacessível ({url}): {e}") from e


def _default_fallback_download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=180) as r:  # noqa: S310 — URL devolvida pelo provider configurado
        return r.read()


def _generate_fallback(fb: dict, prompt: str, out_path: Path, references: list | None, size: str,
                       timeout: float, *, _post=None, _download=None) -> str:
    """Provider REST genérico (JSON, OpenAI-images-compatible: `{data:[{b64_json|url}]}`). Sem suporte
    a `references` (image-to-image) por enquanto — o codex é o único fluxo com isso; um backend de
    fallback sem esse recurso ainda gera texto→imagem normalmente."""
    key = os.environ.get(fb["api_key_env"], "") if fb["api_key_env"] else ""
    if fb["api_key_env"] and not key:
        raise RuntimeError(f"sem a chave de imagem: defina {fb['api_key_env']} no .env.")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": fb["model"], "prompt": prompt, "size": size, "n": 1}
    post = _post or _default_fallback_post
    resp = post(fb["url"], body, headers)
    if not isinstance(resp, dict):
        raise RuntimeError(f"resposta inválida do provider de imagem: {str(resp)[:160]}")
    data = resp.get("data") or resp.get("images") or []
    item = data[0] if isinstance(data, list) and data else {}
    if isinstance(item, dict) and item.get("b64_json"):
        out_path.write_bytes(base64.b64decode(item["b64_json"]))
        return str(out_path)
    url = item.get("url") if isinstance(item, dict) else None
    if isinstance(url, str) and url:
        from okami.core.net_guard import validate_public_url
        validate_public_url(url)                          # anti-SSRF: URL vem do PROVIDER (não-confiável)
        download = _download or _default_fallback_download
        out_path.write_bytes(download(url))
        return str(out_path)
    raise RuntimeError(f"fallback sem imagem: {str(resp)[:200]}")


# --------------------------------------------------------------------- API pública
def generate_image(prompt: str, out: str, *, references: list | None = None, cfg=None,
                   model: str = DEFAULT_MODEL, size: str = DEFAULT_SIZE, quality: str = DEFAULT_QUALITY,
                   chat_model: str = DEFAULT_CHAT_MODEL, token: str | None = None, timeout: float = _TIMEOUT,
                   _send=None, _post=None, _download=None) -> str:
    """Gera (sem `references`) ou EDITA/transforma (com `references`) uma imagem; grava em `out`.

    Codex-first: usa a assinatura ChatGPT/Codex se logada. Se não estiver logada OU a chamada falhar
    (403 Cloudflare, 401, rede) E houver um fallback configurado (`media.image`), cai pro fallback em
    vez de falhar duro. Sem os dois → RuntimeError acionável.
    """
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    codex_token = token if token is not None else _codex_token_or_none()
    codex_error: Exception | None = None
    if codex_token:
        try:
            return _generate_codex(prompt, out_path, references, model, size, quality, chat_model,
                                   codex_token, timeout, _send=_send)
        except Exception as e:  # noqa: BLE001 — codex falhou → tenta o fallback antes de desistir
            codex_error = e
    fb = image_config(_resolve_cfg(cfg))
    if fb is not None:
        return _generate_fallback(fb, prompt, out_path, references, size, timeout,
                                  _post=_post, _download=_download)
    if codex_error is not None:
        raise RuntimeError(f"codex falhou e sem fallback configurado (media.image): {codex_error}") from codex_error
    raise RuntimeError("Sem token Codex p/ gerar imagem (rode: okami login codex) e sem fallback "
                       "configurado (media.image.{backend|url}).")


__all__ = ["generate_image", "image_config", "image_backends", "IMAGE_BACKENDS",
          "DEFAULT_MODEL", "DEFAULT_CHAT_MODEL", "DEFAULT_SIZE", "DEFAULT_QUALITY"]
