"""Hyperlinks OSC-8 no terminal (pesquisa #7 item 8) — paths CLICÁVEIS na TUI.

Terminais modernos (iTerm2, kitty, WezTerm, VS Code) renderizam `ESC]8;;<uri>ESC\\<texto>ESC]8;;ESC\\`
como link clicável. Aqui só p/ `file://` (abrir o arquivo no editor), com sufixo `#L<linha>` quando
útil. FAIL-OPEN: sem TTY, com NO_COLOR, ou em terminal que não suporta → devolve o texto puro (nunca
vaza escape no log/arquivo). `FORCE_HYPERLINK=1` força (útil em teste/captura).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ESC = "\x1b"
_OSC8 = f"{_ESC}]8;;"
_ST = f"{_ESC}\\"


def supports_hyperlinks() -> bool:
    """True só quando faz sentido emitir OSC-8: stdout é um TTY e o usuário não pediu texto cru.
    NO_COLOR desliga (respeita a convenção); FORCE_HYPERLINK liga incondicional (teste/captura)."""
    if os.environ.get("FORCE_HYPERLINK"):
        return True
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return bool(sys.stdout.isatty())
    except Exception:  # noqa: BLE001 — stdout exótico (sem isatty) → conservador: sem link
        return False


def link(target: str, text: str | None = None, line: int | None = None) -> str:
    """Envelopa `text` (ou o próprio path) num hyperlink OSC-8 file:// p/ `target`. `line` vira `#L<n>`.
    Sem suporte (não-TTY/NO_COLOR) → devolve o texto puro, sem nenhum escape."""
    label = text if text is not None else target
    if not supports_hyperlinks():
        return label
    try:
        uri = "file://" + str(Path(target).resolve())
    except Exception:  # noqa: BLE001 — path bizarro → degrada p/ texto puro
        return label
    if line:
        uri += f"#L{int(line)}"
    return f"{_OSC8}{uri}{_ST}{label}{_OSC8}{_ST}"
