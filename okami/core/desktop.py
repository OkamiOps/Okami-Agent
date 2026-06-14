"""Notificação desktop best-effort (pesquisa #7 item 4).

Um lugar só pra "tocar" o usuário no desktop quando algo termina — sem depender de pacote
externo. Sonda os sinks em ordem e usa o primeiro que funcionar:

  1. terminal-notifier (macOS, se instalado)
  2. notify-send (Linux/libnotify, se instalado)
  3. fallback OSC-9: sequência de escape de notificação que terminais modernos (iTerm2,
     kitty, WezTerm, Windows Terminal…) entendem — não precisa de nada instalado.

PRINCÍPIO: nunca levanta. É um aviso, não uma operação crítica; se falhar, devolve False e a vida
segue. Antes de QUALQUER envio externo: redige segredos (redact) e trunca o corpo (notificação não é
lugar pra texto longo nem pra credencial vazada).
"""
from __future__ import annotations

import shutil
import subprocess
import sys

from okami.core.redact import redact

_BODY_MAX = 300
_TITLE_MAX = 120


def _sanitize(s: str) -> str:
    """Remove bytes de CONTROLE (ESC/BEL/CSI/etc.) — senão um corpo/título autorado pelo modelo com
    '\\x07\\x1b]9;...' FECHA o OSC-9 cedo e ABRE uma 2ª notificação spoofada (phishing). Mantém só
    imprimível + \\n/\\t. Vale p/ TODOS os sinks (terminal-notifier/notify-send recebem args também)."""
    return "".join(c for c in (s or "") if c in "\n\t" or (" " <= c < "\x7f") or c > "\x9f")


def desktop_notify(title: str, body: str) -> bool:
    """Mostra uma notificação desktop best-effort. Devolve True no primeiro sink que funcionar,
    False se todos falharem. NUNCA levanta."""
    title = title if isinstance(title, str) else str(title or "")
    body = body if isinstance(body, str) else str(body or "")
    # redige ANTES de truncar; sanitiza bytes de controle DEPOIS (título também — era o vetor OSC-9).
    title = _sanitize(redact(title))[:_TITLE_MAX]
    body = _sanitize(redact(body))[:_BODY_MAX]

    # 1) terminal-notifier (macOS)
    if shutil.which("terminal-notifier"):
        try:
            r = subprocess.run(
                ["terminal-notifier", "-title", title, "-message", body],
                capture_output=True,
                timeout=5,
            )
            if getattr(r, "returncode", 1) == 0:
                return True
        except Exception:  # noqa: BLE001 — best-effort: binário sumiu, timeout, etc.
            pass

    # 2) notify-send (Linux/libnotify)
    if shutil.which("notify-send"):
        try:
            r = subprocess.run(
                ["notify-send", title, body],
                capture_output=True,
                timeout=5,
            )
            if getattr(r, "returncode", 1) == 0:
                return True
        except Exception:  # noqa: BLE001
            pass

    # 3) fallback OSC-9: ESC ] 9 ; <texto> BEL — notificação "nativa" do terminal, zero deps
    try:
        text = f"{title}: {body}" if title else body
        sys.stdout.write(f"\x1b]9;{text}\x07")
        sys.stdout.flush()
        return True
    except Exception:  # noqa: BLE001 — stdout fechado/redirecionado pra algo hostil
        return False
