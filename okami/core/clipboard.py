"""Clipboard via OSC-52 (#8 item 6) — copia pro clipboard do TERMINAL com uma sequência de escape.

Diferente de seleção nativa / pyperclip, OSC-52 atravessa SSH e tmux: o terminal local recebe o texto
mesmo o agente rodando numa máquina remota (casa com o ambiente remoto Tailscale/SSH). Dentro do tmux
é preciso envolver em passthrough DCS p/ o tmux repassar a sequência ao terminal de verdade.
"""
from __future__ import annotations

import base64
import os
import sys


def osc52_copy(text: str, *, tmux: bool | None = None) -> str:
    """Sequência OSC-52 que copia `text` pro clipboard do terminal. `tmux=None` autodetecta via $TMUX."""
    b64 = base64.b64encode((text or "").encode("utf-8", "replace")).decode("ascii")
    seq = f"\x1b]52;c;{b64}\x07"
    if tmux is None:
        tmux = bool(os.environ.get("TMUX"))
    if tmux:                                       # tmux não repassa OSC sozinho → DCS passthrough
        inner = seq.replace("\x1b", "\x1b\x1b")    # escapa cada ESC dentro do passthrough
        seq = f"\x1bPtmux;{inner}\x1b\\"
    return seq


def copy_to_terminal(text: str, *, out=None, tmux: bool | None = None) -> None:
    """Emite a sequência OSC-52 no `out` (default stdout). Best-effort: nunca levanta."""
    out = out if out is not None else sys.stdout
    try:
        out.write(osc52_copy(text, tmux=tmux))
        out.flush()
    except Exception:  # noqa: BLE001 — terminal que não aceita OSC-52: não derruba o REPL
        pass


def repl_copy_text(history, arg: str) -> tuple[str, str]:
    """(texto, rótulo) p/ o /copy do REPL a partir do histórico [(role, text)] (role USER|AGENT).

    arg vazio → última resposta da agente; arg=all|tudo|conversa|chat → conversa inteira."""
    if str(arg or "").strip().lower() in ("all", "tudo", "conversa", "chat"):
        text = "\n\n".join(f"{'você' if r == 'USER' else 'okami'}: {t}"
                           for r, t in history if r in ("USER", "AGENT"))
        return text, "conversa inteira"
    agents = [t for r, t in history if r == "AGENT"]
    return (agents[-1] if agents else ""), "última resposta"
