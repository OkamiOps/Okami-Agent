"""Geração de VÍDEO (#18 — fecha o gap do #17 vs Hermes tools/video_generation_tool.py).

Não há caminho de assinatura p/ vídeo (o Codex faz imagem, não vídeo), então isto é **provider-driven**:
o dono configura um endpoint (FAL/Replicate/Veo/Kling…) em `media.video` e a chave numa env var. Sem
configuração → a tool sai do registro e o CLI avisa (degrada com graça, igual ao resto).

Contrato genérico (cobre os providers comuns):
- POST `url` com `{model, prompt, [image]}` + `Authorization: Bearer <key>`;
- resposta SÍNCRONA → `{"video":{"url":…}}` ou `{"url":…}`;
- resposta ASSÍNCRONA → `{"id":…}` → faz poll em `poll_url/<id>` até `status=completed` + a url do vídeo.
A rede é injetável (`_post`/`_get`/`_download`/`_sleep`) p/ teste offline.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

_POLL_MAX = 60          # nº máximo de polls
_POLL_EVERY = 5.0       # segundos entre polls

# Registry de backends nomeados (paridade Hermes plugins/video_gen/*) — presets de URL/model + capabilities
# refletíveis. O dono escolhe `media.video.backend: veo3` (em vez de digitar a url) e só põe a api_key_env.
# URLs via FAL (gateway comum a vários modelos de vídeo); editável por `media.video.url` se preferir outro.
VIDEO_BACKENDS: dict[str, dict] = {
    "veo3": {"url": "https://fal.run/fal-ai/veo3", "model": "veo-3",
             "poll_url": "https://queue.fal.run/fal-ai/veo3/requests",
             "capabilities": {"audio": True, "max_duration_s": 8, "aspect_ratios": ["16:9", "9:16"],
                              "max_reference_images": 1, "resolutions": ["720p", "1080p"]}},
    "kling": {"url": "https://fal.run/fal-ai/kling-video/v2/master/text-to-video", "model": "kling-2",
              "poll_url": "https://queue.fal.run/fal-ai/kling-video/requests",
              "capabilities": {"audio": False, "max_duration_s": 10, "aspect_ratios": ["16:9", "9:16", "1:1"],
                               "max_reference_images": 1, "resolutions": ["720p"]}},
    "pixverse": {"url": "https://fal.run/fal-ai/pixverse/v4/text-to-video", "model": "pixverse-v4",
                 "poll_url": "https://queue.fal.run/fal-ai/pixverse/requests",
                 "capabilities": {"audio": True, "max_duration_s": 8, "aspect_ratios": ["16:9", "9:16", "1:1"],
                                  "max_reference_images": 1, "resolutions": ["540p", "720p", "1080p"]}},
}


def video_backends() -> list[dict]:
    """Lista os backends nomeados disponíveis (p/ `okami video --list` e descoberta)."""
    return [{"name": k, **v} for k, v in VIDEO_BACKENDS.items()]


def video_config(cfg) -> dict | None:
    """Resolve `media.video`. Aceita um BACKEND nomeado (`backend: veo3`) OU url direta. None se não
    configurado (sem backend válido nem url)."""
    media = (getattr(cfg, "media", None) or {}) if not isinstance(cfg, dict) else (cfg.get("media") or {})
    v = media.get("video") or {}
    backend = (v.get("backend") or "").strip().lower()
    if backend:                                            # preset nomeado
        preset = VIDEO_BACKENDS.get(backend)
        if preset is None:
            return None                                    # backend desconhecido → não configurado
        return {"url": v.get("url") or preset["url"], "model": v.get("model") or preset["model"],
                "api_key_env": v.get("api_key_env", ""), "poll_url": v.get("poll_url") or preset["poll_url"],
                "size": v.get("size", ""), "backend": backend, "capabilities": dict(preset["capabilities"])}
    if not v.get("url"):
        return None
    return {"url": v["url"], "model": v.get("model", ""), "api_key_env": v.get("api_key_env", ""),
            "poll_url": v.get("poll_url", ""), "size": v.get("size", ""), "backend": "", "capabilities": {}}


def _video_url_from(resp: dict) -> str:
    """Extrai a URL do vídeo de uma resposta (cobre {video:{url}}, {url}, {output:{url}})."""
    if not isinstance(resp, dict):
        return ""
    for path in (("video", "url"), ("output", "url")):
        node = resp
        for k in path:
            node = node.get(k) if isinstance(node, dict) else None
        if isinstance(node, str) and node:
            return node
    u = resp.get("url")
    return u if isinstance(u, str) else ""


def _default_post(url, body, headers):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)  # noqa: S310 — URL do config do dono
    try:
        with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as e:            # endpoint morto/inacessível → erro ACIONÁVEL
        raise RuntimeError(f"endpoint de vídeo inacessível ({url}): {e}") from e


def _default_get(url, headers):
    req = urllib.request.Request(url, method="GET", headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"poll de vídeo inacessível ({url}): {e}") from e


def _default_download(url, dest: Path):
    try:
        with urllib.request.urlopen(url, timeout=300) as r:  # noqa: S310 — URL devolvida pelo provider configurado
            dest.write_bytes(r.read())
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"download do vídeo falhou ({url}): {e}") from e


_MAX_IMAGE_BYTES = 25 * 1024 * 1024     # teto da imagem base (evita OOM no base64)


def generate_video(cfg, prompt: str, out: str, *, image: str | None = None,
                   _post=None, _get=None, _download=None, _sleep=None, _validate=None) -> str:
    """Gera um vídeo a partir de `prompt` (e opcionalmente uma imagem base) → salva em `out`. Devolve o
    caminho. Sem config → RuntimeError("configure media.video…"); sem a chave → RuntimeError(env).
    A URL de download (vinda do PROVIDER, não-confiável) passa pelo net_guard anti-SSRF antes de baixar."""
    vc = video_config(cfg)
    if vc is None:
        raise RuntimeError("geração de vídeo não configurada — configure media.video.{url,model,api_key_env}.")
    key = os.environ.get(vc["api_key_env"], "") if vc["api_key_env"] else ""
    if vc["api_key_env"] and not key:
        raise RuntimeError(f"sem a chave de vídeo: defina {vc['api_key_env']} no .env.")
    post = _post or _default_post
    get = _default_get if _get is None else _get
    download = _download or _default_download
    sleep = _sleep or __import__("time").sleep
    if _validate is None:                                  # default: valida a URL do provider (anti-SSRF)
        from okami.core.net_guard import validate_public_url as _validate

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": vc["model"], "prompt": prompt}
    if vc["size"]:
        body["size"] = vc["size"]
    if image:
        import base64
        ip = Path(image)
        if ip.stat().st_size > _MAX_IMAGE_BYTES:           # imagem gigante → recusa (anti-OOM)
            raise RuntimeError(f"imagem base grande demais ({ip.stat().st_size} bytes > {_MAX_IMAGE_BYTES}).")
        body["image"] = base64.b64encode(ip.read_bytes()).decode("ascii")

    resp = post(vc["url"], body, headers)
    url = _video_url_from(resp)
    if not isinstance(resp, dict):                             # provider devolveu corpo não-dict (ex.: JSON `null`)
        raise RuntimeError(f"resposta inválida do provider de vídeo: {str(resp)[:160]}")
    if not url and resp.get("id") and vc["poll_url"]:          # assíncrono → poll
        job = resp["id"]
        for _ in range(_POLL_MAX):
            sleep(_POLL_EVERY)
            st = get(f"{vc['poll_url'].rstrip('/')}/{job}", headers)
            if (st.get("status") or "").lower() in ("completed", "succeeded", "success", "done"):
                url = _video_url_from(st)
                break
            if (st.get("status") or "").lower() in ("failed", "error", "canceled"):
                raise RuntimeError(f"geração de vídeo falhou: {str(st)[:160]}")
    if not url:
        raise RuntimeError(f"resposta sem URL de vídeo: {str(resp)[:160]}")
    _validate(url)                                         # anti-SSRF: provider não redireciona p/ file://, IP interno…
    dest = Path(out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    download(url, dest)
    return str(dest)


__all__ = ["video_config", "video_backends", "generate_video", "VIDEO_BACKENDS"]
