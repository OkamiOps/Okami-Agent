"""Helper compartilhado: embute um PNG local como bloco de imagem de ToolResult.content (o modelo VÊ a
imagem, não só o caminho). Extraído de computer_use.py p/ ser reusado por browse(action=screenshot)."""

from __future__ import annotations


def image_block(path: str, *, max_bytes: int = 6 * 1024 * 1024):
    """Lê `path` (PNG) e devolve o content-block de imagem, ou None (arquivo vazio/grande demais/erro —
    best-effort, nunca derruba a tool que chamou)."""
    try:
        import base64
        from pathlib import Path as _P
        raw = _P(path).read_bytes()
        if not raw or len(raw) > max_bytes:
            return None
        uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        return [{"type": "image_url", "image_url": {"url": uri}}]
    except Exception:  # noqa: BLE001
        return None
