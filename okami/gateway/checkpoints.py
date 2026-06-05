"""Checkpoints de arquivo (estilo Hermes) — snapshot ANTES de cada escrita → rollback.

Rede de segurança complementar ao go/no-go (§12): toda escrita de `write_file` registra o estado
ANTERIOR do arquivo num journal append-only (`<ws>/.okami/checkpoints/journal.jsonl`). `rollback(n)`
desfaz as últimas n escritas (restaura o conteúdo de antes, ou apaga o arquivo se ele não existia).
Best-effort: se o snapshot falhar, a escrita segue normal (nunca quebra o agente).
"""

from __future__ import annotations

import json
from pathlib import Path


class Checkpoints:
    def __init__(self, workspace):
        self.ws = Path(workspace)
        self.dir = self.ws / ".okami" / "checkpoints"
        self.journal = self.dir / "journal.jsonl"

    _MAX_SNAP = 2_000_000          # não captura arquivo gigante no journal (cap de tamanho)

    def _safe(self, rel: str):
        """Resolve `rel` DENTRO do workspace (#5): rel absoluto/escape → None (não snapshota fora).
        Também recusa caminho sensível (não captura segredo em plaintext no journal)."""
        from okami.core.file_safety import safe_path
        from okami.core.tools import _SENSITIVE_PATH
        try:
            p = safe_path(self.ws, rel)
        except ValueError:                          # PathEscape (rel absoluto / ../) → fora do jail
            return None
        if _SENSITIVE_PATH.search(rel) or _SENSITIVE_PATH.search(str(p)):
            return None                             # .env/.ssh/.aws/credenciais/*.pem → não captura
        return p

    def snapshot(self, rel: str) -> None:
        """Grava o estado ATUAL de `rel` (antes de uma escrita) — jailed + sem segredo + cap de tamanho."""
        p = self._safe(rel)
        if p is None:
            return
        before = None
        if p.exists():
            try:
                if p.stat().st_size > self._MAX_SNAP:   # grande demais → não captura (limite)
                    return
                before = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.journal.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"path": rel, "before": before, "existed": before is not None},
                               ensure_ascii=False) + "\n")

    def entries(self) -> list[dict]:
        if not self.journal.exists():
            return []
        out = []
        for ln in self.journal.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
        return out

    def rollback(self, n: int = 1) -> list[str]:
        """Reverte as últimas n escritas; devolve os caminhos revertidos."""
        ents = self.entries()
        if not ents or n <= 0:
            return []
        undone = ents[-n:]
        for e in reversed(undone):
            p = self._safe(e.get("path", ""))           # #5: valida a entrada ANTES de escrever (anti-tamper)
            if p is None:
                continue                                # entrada adulterada / aponta p/ fora → pula
            if e.get("existed"):
                from okami.core.file_safety import write_text_atomic
                write_text_atomic(p, e.get("before") or "")   # rollback ATÔMICO
            elif p.exists():
                p.unlink()                              # não existia antes → apaga
        keep = ents[: len(ents) - len(undone)]
        self.journal.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in keep),
                                encoding="utf-8", newline="\n")
        return [e["path"] for e in undone]
