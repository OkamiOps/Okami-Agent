"""Visão emprestada (pesquisa #6 item 4) — roteia uma imagem por um modelo AUXILIAR multimodal p/
dar "olhos" a um modelo de texto. OCR, descrição de screenshot, leitura de gráfico, etc.

Reusa o aux routing (task 'vision'): config `auxiliary.vision: {provider, model}` aponta um modelo
com visão; o modelo principal de texto nem precisa ser multimodal.
"""
from __future__ import annotations

import base64
from pathlib import Path

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
         ".webp": "image/webp", ".bmp": "image/bmp"}
_MAX_BYTES = 20 * 1024 * 1024     # 20MB: imagem maior que isto não é enviada (provável engano)

_VISION_SYSTEM = ("Você é os OLHOS de outro agente. Descreva a imagem com PRECISÃO e FIDELIDADE para "
                  "a pergunta — transcreva texto (OCR) literalmente, leia números/rótulos, não invente "
                  "o que não dá pra ver.")


def _sniff_mime_from_bytes(raw: bytes) -> str | None:
    """MIME por magic-byte, ou None se não reconhecer. Detecção por NOME (suffix) é não-confiável quando
    a plataforma mente o content-type (Discord serve PNG como webp); a Anthropic valida media_type×bytes
    e dá 400 se divergir. Por isso checamos os bytes (#11)."""
    if not raw:
        return None
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.startswith(b"BM"):
        return "image/bmp"
    if len(raw) >= 12 and raw[4:8] == b"ftyp" and raw[8:12] in (
            b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis"):
        return "image/heic"
    return None


def _data_uri(path: Path) -> str:
    raw = path.read_bytes()
    # sniff dos bytes tem prioridade sobre o suffix (sufixo mentido → 400 da Anthropic); cai no suffix se
    # o sniff não reconhecer.
    mime = _sniff_mime_from_bytes(raw) or _MIME.get(path.suffix.lower(), "image/png")
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def build_vision_messages(prompt: str, data_uri: str) -> list[dict]:
    """Mensagens multimodais (texto + imagem) no formato OpenAI-compatible."""
    return [
        {"role": "system", "content": _VISION_SYSTEM},
        {"role": "user", "content": [
            {"type": "text", "text": prompt or "Descreva esta imagem em detalhe."},
            {"type": "image_url", "image_url": {"url": data_uri}}]},
    ]


def analyze_image(cfg, image_path: str, prompt: str, *, complete=None) -> str:
    """Analisa a imagem via modelo auxiliar (task 'vision'). `complete(cfg, task, msgs, **kw)`
    injetável. Erros (arquivo ausente, grande demais) viram mensagem acionável (não exceção)."""
    p = Path(image_path)
    if not p.exists():
        return f"imagem não encontrada: {image_path}"
    if p.suffix.lower() not in _MIME:
        return f"formato não suportado p/ visão: {p.suffix} (use png/jpg/gif/webp)."
    try:
        if p.stat().st_size > _MAX_BYTES:
            return f"imagem grande demais (> {_MAX_BYTES // (1024 * 1024)}MB) p/ análise de visão."
        uri = _data_uri(p)
    except OSError as e:
        return f"erro ao ler a imagem: {e}"
    if complete is None:
        from okami.llm.aux import aux_complete as complete
    return complete(cfg, "vision", build_vision_messages(prompt, uri), max_tokens=1000)
