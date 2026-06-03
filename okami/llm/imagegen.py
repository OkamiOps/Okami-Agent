"""Geração de imagem (§13) — gpt-image-2 via ASSINATURA do Codex/ChatGPT (token OAuth nativo).

DOIS FLUXOS (pedido do usuário):
- **sem referência** (`/v1/images/generations`): texto → imagem nova.
- **com referência** (`/v1/images/edits`): o agente MANDA a(s) imagem(ns) recebida(s) + o prompt p/ o
  gpt-image-2 (ex.: "vire um infográfico"). O agente NÃO edita o arquivo — quem gera é o modelo.

Reusa o access_token do Codex (`okami login codex`). EXPERIMENTAL — endpoints/escopo podem variar;
por isso `url`/`edit_url`/`model` são configuráveis.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import secrets
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://api.openai.com/v1/images/generations"
DEFAULT_EDIT_URL = "https://api.openai.com/v1/images/edits"
DEFAULT_MODEL = "gpt-image-2"


def _token() -> str:
    from okami.llm import oauth
    tok = oauth.codex_access_token()
    if not tok:
        raise RuntimeError("Sem token Codex p/ gerar imagem. Rode: okami login codex")
    return tok


def _save_result(data: dict, out: Path) -> str:
    item = (data.get("data") or [{}])[0]
    out.parent.mkdir(parents=True, exist_ok=True)
    if item.get("b64_json"):
        out.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=180) as ir:  # noqa: S310
            out.write_bytes(ir.read())
    else:
        raise RuntimeError(f"resposta sem imagem: {str(data)[:200]}")
    return str(out)


def _generate(prompt: str, out: Path, model: str, size: str, url: str, token: str, timeout: float) -> str:
    body = json.dumps({"model": model, "prompt": prompt, "size": size, "n": 1}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return _save_result(json.loads(r.read().decode("utf-8")), out)


def _edit(prompt: str, out: Path, references: list, model: str, size: str, url: str,
          token: str, timeout: float) -> str:
    """Multipart p/ /images/edits: manda a(s) imagem(ns) de referência + o prompt."""
    boundary = "----okami" + secrets.token_hex(12)
    parts: list[bytes] = []

    def field(name: str, value: str) -> bytes:
        return (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode()

    parts += [field("model", model), field("prompt", prompt), field("size", size), field("n", "1")]
    for ref in references:
        p = Path(ref)
        mime = mimetypes.guess_type(str(p))[0] or "image/png"
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="image[]"; '
                      f'filename="{p.name}"\r\nContent-Type: {mime}\r\n\r\n').encode())
        parts += [p.read_bytes(), b"\r\n"]
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(url, data=b"".join(parts), method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return _save_result(json.loads(r.read().decode("utf-8")), out)


def generate_image(prompt: str, out: str, *, references: list | None = None,
                   model: str = DEFAULT_MODEL, size: str = "1024x1024", url: str = DEFAULT_URL,
                   edit_url: str = DEFAULT_EDIT_URL, token: str | None = None,
                   timeout: float = 180.0) -> str:
    """Gera (sem ref) ou EDITA/transforma (com `references`) uma imagem; grava em `out`."""
    token = token or _token()
    out_path = Path(out)
    if references:                                    # fluxo COM referência → /images/edits
        return _edit(prompt, out_path, references, model, size, edit_url, token, timeout)
    return _generate(prompt, out_path, model, size, url, token, timeout)   # SEM referência
