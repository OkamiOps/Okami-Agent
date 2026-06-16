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
import tempfile
import time
from pathlib import Path

# Lock promovido p/ o núcleo (okami/core/filelock.py) — re-exportado aqui p/ compat de import.
from okami.core.filelock import _HELD, _cleanup_held_locks, _FileLock, _proc_start  # noqa: F401


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
        # tmp ÚNICO por escrita (pid+rand): o nome fixo 'sessions.json.tmp' fazia 2 processos colidirem no
        # mesmo arquivo → o os.replace do 2º estourava FileNotFoundError (o 1º já tinha movido o tmp).
        fd, tmp_name = tempfile.mkstemp(dir=str(self.dir), prefix=".sessions-", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(store, ensure_ascii=False))
            os.replace(tmp_name, self._store_path())      # rename atômico
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

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

    def add_usage(self, chat_id, usage: dict, *, served_by: str = "") -> dict:
        """Acumula os tokens do turno nos metadados da sessão (sob lock cross-process). `usage` é o
        dict de `CanonicalUsage.to_dict()`. Custo é DERIVADO na hora de mostrar (preço muda retroativo)."""
        if not usage:
            return self.entry(chat_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        with _FileLock(self._store_path()):
            store = self.load_store()
            e = store.setdefault(str(chat_id), {})
            acc = e.setdefault("usage", {})
            for k, v in usage.items():
                acc[k] = int(acc.get(k, 0)) + int(v or 0)
            if served_by:
                e["served_by"] = served_by
            e["updated_at"] = self._clock()
            self._save_store(store)
        return e

    def ids(self) -> list[str]:
        return list(self.load_store().keys())

    # ----------------------------------------------------------------- transcript (append-only)
    def append(self, chat_id, role: str, text: str) -> str:
        """Acrescenta UM nó ao transcript e atualiza os metadados — TUDO sob UM lock por chat (P0.5).

        Antes: lia node_count, escrevia e atualizava em passos separados → duas escritas concorrentes
        pegavam o mesmo node_count (id duplicado / metadado perdido). Agora o lock por chat serializa
        a transação inteira (count fresco → append → update_entry)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        ts = self._clock()
        with _FileLock(self._tx_path(chat_id)):          # serializa a transação do MESMO chat
            n = int(self.entry(chat_id).get("node_count", 0))   # node_count FRESCO sob o lock
            node = {"id": f"{chat_id}-{n}", "parentId": (f"{chat_id}-{n - 1}" if n else None),
                    "role": role, "text": text, "ts": ts}
            with self._tx_path(chat_id).open("a", encoding="utf-8") as f:
                f.write(json.dumps(node, ensure_ascii=False) + "\n")
            self.update_entry(chat_id, node_count=n + 1, last_node_id=node["id"], last_role=role,
                              last_interaction_at=ts)     # store lock (alvo diferente → sem deadlock)
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

    # ----------------------------------------------------------------- session service (/sessions /resume /export)
    def archives(self, chat_id) -> list[dict]:
        """Sessões ARQUIVADAS (por /new) deste chat: [{ts, name, turns}], mais nova primeiro."""
        out = []
        for p in self.dir.glob(f"{chat_id}.*.reset.jsonl"):
            try:
                ts = int(p.name.split(".")[-3])
            except (ValueError, IndexError):
                ts = 0
            turns = len(p.read_text(encoding="utf-8", errors="ignore").splitlines()) // 2
            out.append({"ts": ts, "name": p.name, "turns": turns})
        return sorted(out, key=lambda a: a["ts"], reverse=True)

    def resume(self, chat_id, name: str) -> list[tuple[str, str]]:
        """Retoma uma sessão arquivada: arquiva a atual e torna `name` o transcript ativo. Devolve o histórico."""
        arch = self.dir / name
        if not name.startswith(f"{chat_id}.") or not arch.exists():
            raise FileNotFoundError(name)
        self.reset(chat_id)                          # arquiva a sessão atual antes de trocar
        arch.rename(self._tx_path(chat_id))          # a arquivada vira a ativa
        nodes = self.read(chat_id)
        self.update_entry(chat_id, node_count=len(nodes),
                          last_node_id=(nodes[-1].get("id") if nodes else None),
                          last_role=(nodes[-1].get("role") if nodes else None))
        return [(n.get("role", ""), n.get("text", "")) for n in nodes if n.get("role")]

    def export(self, chat_id, path) -> Path:
        """Exporta o transcript como Markdown legível. Devolve o caminho escrito."""
        nodes = self.read(chat_id)
        lines = [f"# Conversa {chat_id}\n"]
        for n in nodes:
            who = {"USER": "você", "AGENTE": "okami", "SUMMARY": "— resumo —"}.get(n.get("role", ""),
                                                                                   n.get("role", ""))
            lines.append(f"**{who}:** {n.get('text', '')}\n")
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        return out

    # ----------------------------------------------------------------- maintenance (poda)
    def prune(self, max_sessions: int = 500, max_age_days: float = 30.0) -> int:
        """Estilo OpenClaw session.maintenance: remove sessões velhas/excedentes (store + transcript)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        # read-modify-write sob _FileLock (igual update_entry/add_usage): sem o lock, um prune concorrente
        # com um update_entry sobrescrevia a gravação do outro (lost update) e/ou colidia no os.replace.
        with _FileLock(self._store_path()):
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
