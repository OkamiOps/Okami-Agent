"""Sessões em 2 CAMADAS (estilo OpenClaw, §13) — metadados + transcript append-only.

Por que 2 camadas (e não 1 JSON por chat):
- **Store** (`sessions.json`): mapa pequeno e mutável `chat_id -> entry` (sessionId, contadores,
  timestamps, yolo/overlay/resume_attempts). Reescrito ATOMICAMENTE (temp+replace) — é minúsculo.
- **Transcript** (`<chat>.jsonl`): APPEND-ONLY, uma linha por turno, em árvore (`id`/`parentId`).
  Nunca reescreve a conversa inteira → crash-safe (uma queda no meio perde no máx. a última linha)
  e escalável (conversa gigante não vira um write gigante). Suporta nós de SUMMARY (compaction §6.4).

O gateway (§13) usa isto: rebuild do histórico = ler a cauda do transcript; gravar um turno = append.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

class _FileLock:
    """Lock cross-platform por arquivo (.lock atômico O_EXCL) — concorrência multi-processo.
    Best-effort: se não conseguir em `timeout`s segue mesmo assim (não trava o agente); limpa lock velho."""

    def __init__(self, target: Path, timeout: float = 10.0, stale: float = 60.0):
        self.lock = Path(str(target) + ".lock")
        self.timeout, self.stale = timeout, stale

    def __enter__(self):
        start = time.time()
        while True:
            try:
                fd = os.open(str(self.lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.lock.stat().st_mtime > self.stale:
                        self.lock.unlink()                # lock órfão de processo morto → remove
                        continue
                except OSError:
                    pass
                if time.time() - start > self.timeout:
                    return self                           # desiste e segue (best-effort)
                time.sleep(0.03)

    def __exit__(self, *exc):
        try:
            self.lock.unlink()
        except OSError:
            pass


class TranscriptStore:
    def __init__(self, root, *, subdir: str = "sessions", clock=time.time):
        self.dir = Path(root) / ".okami" / subdir   # subdir: "sessions" (DM) | "groups" (§10)
        self._clock = clock                      # injetável p/ teste determinístico

    # ----------------------------------------------------------------- store (metadados)
    def _store_path(self) -> Path:
        return self.dir / "sessions.json"

    def _tx_path(self, chat_id) -> Path:
        return self.dir / f"{chat_id}.jsonl"

    def load_store(self) -> dict:
        p = self._store_path()
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_store(self, store: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self._store_path().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8", newline="\n")
        os.replace(tmp, self._store_path())      # rename atômico

    def entry(self, chat_id) -> dict:
        return self.load_store().get(str(chat_id), {})

    def update_entry(self, chat_id, **fields) -> dict:
        self.dir.mkdir(parents=True, exist_ok=True)
        with _FileLock(self._store_path()):          # read-modify-write atômico entre processos
            store = self.load_store()
            e = store.setdefault(str(chat_id), {})
            e.update(fields)
            e["updated_at"] = self._clock()
            self._save_store(store)
        return e

    def ids(self) -> list[str]:
        return list(self.load_store().keys())

    # ----------------------------------------------------------------- transcript (append-only)
    def append(self, chat_id, role: str, text: str) -> str:
        """Acrescenta UM nó ao transcript (append-only) e atualiza os metadados. Devolve o id do nó."""
        self.dir.mkdir(parents=True, exist_ok=True)
        e = self.entry(chat_id)
        n = int(e.get("node_count", 0))
        ts = self._clock()
        node = {"id": f"{chat_id}-{n}", "parentId": (f"{chat_id}-{n - 1}" if n else None),
                "role": role, "text": text, "ts": ts}
        with self._tx_path(chat_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")
        self.update_entry(chat_id, node_count=n + 1, last_node_id=node["id"], last_role=role,
                          last_interaction_at=ts)
        return node["id"]

    def read(self, chat_id, limit: int | None = None) -> list[dict]:
        p = self._tx_path(chat_id)
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        if limit is not None:
            lines = lines[-limit:]
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:        # linha truncada por um crash no meio do append → ignora
                pass
        return out

    def history(self, chat_id, limit: int = 16) -> list[tuple[str, str]]:
        """Histórico recente como (papel, texto). Papel = USER/AGENTE (DM) ou o id do agente (grupo §10).
        A partir do último nó SUMMARY (compaction §6.4): o resumo SUBSTITUI o prefixo antigo."""
        nodes = self.read(chat_id)
        last_sum = max((i for i, n in enumerate(nodes) if n.get("role") == "SUMMARY"), default=-1)
        if last_sum >= 0:
            nodes = nodes[last_sum:]                  # resumo + o que veio depois
        return [(n.get("role", ""), n.get("text", "")) for n in nodes[-limit:] if n.get("role")]

    def compact(self, chat_id, summary: str) -> str:
        """Compaction §6.4: append de um nó SUMMARY (resume o que veio antes — nada se perde, o
        transcript completo continua no disco; só o REBUILD passa a usar o resumo)."""
        return self.append(chat_id, "SUMMARY", summary)

    def reset(self, chat_id) -> None:
        """/new — ARQUIVA o transcript (não apaga) e zera a contagem; preserva yolo/overlay."""
        p = self._tx_path(chat_id)
        if p.exists():
            try:
                p.rename(self.dir / f"{chat_id}.{int(self._clock())}.reset.jsonl")
            except OSError:
                pass
        self.update_entry(chat_id, node_count=0, last_node_id=None, last_role=None)

    # ----------------------------------------------------------------- maintenance (poda)
    def prune(self, max_sessions: int = 500, max_age_days: float = 30.0) -> int:
        """Estilo OpenClaw session.maintenance: remove sessões velhas/excedentes (store + transcript)."""
        store = self.load_store()
        if not store:
            return 0
        items = sorted(store.items(), key=lambda kv: kv[1].get("updated_at", 0), reverse=True)
        cutoff = self._clock() - max_age_days * 86400
        keep, removed = {}, 0
        for i, (cid, e) in enumerate(items):
            if i >= max_sessions or e.get("updated_at", 0) < cutoff:
                try:
                    self._tx_path(cid).unlink()
                except OSError:
                    pass
                removed += 1
            else:
                keep[cid] = e
        if removed:
            self._save_store(keep)
        return removed
