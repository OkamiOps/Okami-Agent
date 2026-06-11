"""Fila de aprovação de escrita de memória (porta do write_approval do Hermes).

O review em BACKGROUND escreve memória sem ninguém olhando. Com `memory.write_approval: true`,
a escrita de origem automática fica STAGED em `<home>/.okami/pending/memory/<id>.json` e o dono
revisa pelo chat (/memory pending|approve|reject). Sobrevive a restart (arquivo, não RAM).
Aprovar aplica no tier core (MEMORY.md / USER.md — sempre injetados), que é onde a escrita
automática mais machuca quando erra.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class PendingStore:
    """Fila durável de escritas de memória aguardando aprovação do dono."""

    def __init__(self, home: Path | str):
        self.home = Path(home)
        self.dir = self.home / ".okami" / "pending" / "memory"

    def stage(self, kind: str, text: str, *, origin: str = "auto") -> str:
        """Enfileira uma escrita (kind: 'fact' → MEMORY.md | 'user' → USER.md). Retorna o id."""
        self.dir.mkdir(parents=True, exist_ok=True)
        pid = f"{int(time.time() * 1000):x}"
        n = 0
        while (self.dir / f"{pid}.json").exists():    # 2 stages no mesmo ms → sufixo (não sobrescreve)
            n += 1
            pid = f"{int(time.time() * 1000):x}-{n}"
        (self.dir / f"{pid}.json").write_text(
            json.dumps({"id": pid, "kind": kind, "text": text, "origin": origin,
                        "staged_at": time.time()}, ensure_ascii=False),
            encoding="utf-8", newline="\n")
        return pid

    def pending(self) -> list[dict]:
        out = []
        if not self.dir.exists():
            return out
        for f in sorted(self.dir.glob("*.json")):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue                                  # entrada corrompida não trava a fila
        return out

    def _take(self, which: str) -> list[dict]:
        items = self.pending()
        if which != "all":
            items = [i for i in items if i.get("id") == which]
        return items

    def approve(self, which: str = "all") -> int:
        """Aplica (MEMORY.md/USER.md no tier core) e remove da fila. Retorna quantas aplicou."""
        from okami.memory import files as memfiles
        n = 0
        for item in self._take(which):
            ok = (memfiles.append_user(self.home, item["text"]) if item.get("kind") == "user"
                  else memfiles.append_fact(self.home, item["text"]))
            (self.dir / f"{item['id']}.json").unlink(missing_ok=True)
            n += 1 if ok else 0
        return n

    def reject(self, which: str = "all") -> int:
        """Descarta sem aplicar. Retorna quantas removeu."""
        n = 0
        for item in self._take(which):
            (self.dir / f"{item['id']}.json").unlink(missing_ok=True)
            n += 1
        return n
