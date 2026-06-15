"""Recuperação REATIVA de erro de provider (#10) — conserta o request e re-tenta O MESMO provider 1×
ANTES do failover.

Importa porque o Okami é OAuth/assinatura-only e NÃO tem key pool p/ rotacionar: um 400/401 consertável
hoje pula direto pro fallback e PERDE a assinatura naquele turno. As duas recuperações que de fato
disparam no Okami:
- imagem grande demais (teto por-imagem da Anthropic) → encolhe a imagem nativa e re-tenta.
- 401 OAuth com token NÃO-expirado (revogado/relógio-torto) → força refresh do token e re-tenta.
(thinking-signature/beta-1M/max_completion_tokens NÃO se aplicam: o Okami não replaya reasoning, não
manda o beta 1M, e não envia max_tokens — então esses 400s não ocorrem aqui.)
"""
from __future__ import annotations

import base64
import io
import re

_IMG_TOO_BIG = re.compile(
    r"image.{0,30}(exceeds|too large|too big)|exceeds.{0,25}(maximum|max).{0,20}(image|size)"
    r"|image.{0,20}\d+\s*(MB|megabyte|mb)|image dimensions.{0,25}exceed|max(imum)? image (size|dimension)",
    re.I,
)
_MAX_IMG_DIM = re.compile(r"(\d{3,5})\s*(px|pixels)?\s*(maximum|max|or less)?", re.I)


def is_image_too_large(exc) -> bool:
    """True se o erro do provider é 'imagem excede o teto' (por-imagem/dimensão)."""
    return bool(_IMG_TOO_BIG.search(str(exc)))


def shrink_images(messages, *, max_dim: int = 1568) -> list[dict]:
    """Encolhe partes image_url data-URL com lado maior > max_dim, re-encodando. Best-effort: sem PIL
    ou parte não-decodificável → deixa como está. Devolve cópia se mudou algo, senão a lista original."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 — sem Pillow: não dá p/ encolher
        return messages
    changed = False
    out = []
    for m in messages:
        c = m.get("content") if isinstance(m, dict) else None
        if not isinstance(c, list):
            out.append(m)
            continue
        parts = []
        for p in c:
            np = _shrink_part(p, Image, max_dim)
            changed = changed or (np is not p)
            parts.append(np)
        out.append({**m, "content": parts})
    return out if changed else messages


def _shrink_part(p, image_mod, max_dim: int):
    if not (isinstance(p, dict) and p.get("type") == "image_url"):
        return p
    url = (p.get("image_url") or {}).get("url", "")
    if not isinstance(url, str) or not url.startswith("data:"):
        return p
    try:
        header, b64 = url.split(",", 1)
        img = image_mod.open(io.BytesIO(base64.b64decode(b64)))
        if max(img.size) <= max_dim:
            return p
        img.thumbnail((max_dim, max_dim))                 # mantém proporção, lado maior = max_dim
        fmt = "PNG" if "png" in header.lower() else "JPEG"
        if fmt == "JPEG" and img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        mime = "image/png" if fmt == "PNG" else "image/jpeg"
        new_url = f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
        return {**p, "image_url": {**(p.get("image_url") or {}), "url": new_url}}
    except Exception:  # noqa: BLE001 — imagem corrompida/formato exótico → não mexe
        return p


def refresh_oauth(pc) -> bool:
    """Força refresh do token OAuth do provider (p/ um 401). True se refrescou (vale re-tentar o mesmo
    provider). Hoje cobre o codex_oauth (rota de assinatura principal); claude_cli é gerido pelo CLI."""
    from okami.llm import oauth
    transport = getattr(pc, "transport", "") or ""
    try:
        if transport == "codex_oauth":
            return bool(oauth.force_refresh_codex())
        ocfg = getattr(pc, "oauth", None)
        if ocfg:
            return bool(oauth.force_refresh(getattr(pc, "name", ""), ocfg))
    except Exception:  # noqa: BLE001 — refresh é best-effort; falhou → cai no fluxo normal (fallback)
        return False
    return False
