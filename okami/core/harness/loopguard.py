"""Detector de NÃO-PROGRESSO por OUTPUT (paridade OpenClaw tool-loop-detection.ts).

O anti-loop do harness pega AÇÃO repetida (mesmos args). Falta o caso do OpenClaw: a tool roda, os
args mudam OU não, mas o RESULTADO é byte-a-byte o mesmo várias vezes seguidas — é I/O girando à toa
(poll de processo que não anda, read de arquivo que não muda). Aqui contamos repetição por OUTPUT,
por tool, resetando quando o resultado muda (= progresso de verdade)."""

from __future__ import annotations

import hashlib

_SIG_CAP = 4096        # hash só dos primeiros N chars (poll/estado muda no começo; barato e suficiente)


def output_signature(output: str) -> str:
    """Assinatura estável do output: normaliza espaços e capa o tamanho → mesma saída ⇒ mesma sig."""
    norm = " ".join((output or "").split())[:_SIG_CAP]
    return hashlib.blake2b(norm.encode("utf-8", "ignore"), digest_size=12).hexdigest()


class ProgressTracker:
    """Conta quantas vezes SEGUIDAS uma tool devolveu a MESMA saída. 0 = primeira vez (ou mudou)."""

    def __init__(self):
        self._last: dict[str, str] = {}     # tool → última assinatura de saída
        self._streak: dict[str, int] = {}   # tool → repetições consecutivas da MESMA saída

    def stalled_count(self, tool: str, output: str) -> int:
        sig = output_signature(output)
        if self._last.get(tool) == sig:
            self._streak[tool] = self._streak.get(tool, 0) + 1
        else:
            self._last[tool] = sig
            self._streak[tool] = 0
        return self._streak[tool]
