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

    def snapshot(self, rel: str) -> None:
        """Grava o estado ATUAL de `rel` (antes de uma escrita)."""
        p = self.ws / rel
        before = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else None
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
            p = self.ws / e["path"]
            if e.get("existed"):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(e.get("before") or "", encoding="utf-8", newline="\n")
            elif p.exists():
                p.unlink()                              # não existia antes → apaga
        keep = ents[: len(ents) - len(undone)]
        self.journal.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in keep),
                                encoding="utf-8", newline="\n")
        return [e["path"] for e in undone]
