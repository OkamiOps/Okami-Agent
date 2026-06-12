"""Índice FTS5 sobre os TRANSCRIPTS de sessão (pesquisa #6 item 10).

Doutrina (Hermes): memória = preferência durável; histórico de TAREFA = busca de sessão. Os
transcripts (ativos + arquivados por /new) ficam em <home>/.okami/sessions/*.jsonl mas eram
irrecuperáveis depois de compactar/arquivar. Aqui um índice FTS5 dedicado (separado da memória
semântica) deixa a agente reabrir o que foi conversado/decidido em qualquer sessão.

Reindex INCREMENTAL por mtime (arquivo inalterado não é relido). Best-effort: erro de FTS → degrada.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

_WORD = re.compile(r"\w+", re.UNICODE)


class SessionIndex:
    def __init__(self, home, *, subdir: str = "sessions"):
        self.sessions_dir = Path(home) / ".okami" / subdir
        self.db_path = Path(home) / ".okami" / "session_index.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._init()

    def _init(self) -> None:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS indexed_files(name TEXT PRIMARY KEY, mtime REAL, size INTEGER)")
        self.conn.executescript(
            "CREATE VIRTUAL TABLE IF NOT EXISTS messages USING fts5("
            "chat_id, session, role, text, ts UNINDEXED, node_id UNINDEXED, "
            "tokenize='unicode61 remove_diacritics 2');")
        self.conn.commit()

    @staticmethod
    def _chat_id_of(name: str) -> str:
        """'100.jsonl' → '100'; '100.1700.reset.jsonl' → '100'."""
        return name.split(".", 1)[0]

    def reindex(self) -> int:
        """Indexa transcripts novos/alterados (incremental por mtime+size). Retorna nº de mensagens
        (re)indexadas nesta passada (0 = nada mudou)."""
        if not self.sessions_dir.exists():
            return 0
        indexed = {r[0]: (r[1], r[2]) for r in self.conn.execute(
            "SELECT name, mtime, size FROM indexed_files")}
        total = 0
        for p in sorted(self.sessions_dir.glob("*.jsonl")):
            try:
                stt = p.stat()
            except OSError:
                continue
            prev = indexed.get(p.name)
            if prev and abs(prev[0] - stt.st_mtime) < 1e-6 and prev[1] == stt.st_size:
                continue                              # inalterado → pula
            # mudou (ou novo): re-indexa o arquivo inteiro (apaga o que tinha dele antes)
            self.conn.execute("DELETE FROM messages WHERE session = ?", (p.name,))
            chat_id = self._chat_id_of(p.name)
            rows = []
            for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    node = json.loads(ln)
                except ValueError:
                    continue
                txt = (node.get("text") or "").strip()
                if not txt or node.get("role") == "SUMMARY":   # resumo não é "o que foi dito"
                    continue
                rows.append((chat_id, p.name, node.get("role", ""), txt,
                             node.get("ts", 0), node.get("id", "")))
            if rows:
                self.conn.executemany(
                    "INSERT INTO messages(chat_id, session, role, text, ts, node_id) "
                    "VALUES (?,?,?,?,?,?)", rows)
                total += len(rows)
            self.conn.execute(
                "INSERT OR REPLACE INTO indexed_files(name, mtime, size) VALUES (?,?,?)",
                (p.name, stt.st_mtime, stt.st_size))
        self.conn.commit()
        return total

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Busca FTS5 nas mensagens. Retorna [{chat_id, session, role, text, ts, snippet}] por
        relevância. Query vazia → []."""
        q = (query or "").strip()
        if not q:
            return []
        match = " OR ".join(w for w in _WORD.findall(q.lower()) if w)
        if not match:
            return []
        try:
            rows = self.conn.execute(
                "SELECT chat_id, session, role, text, ts, "
                "snippet(messages, 3, '«', '»', '…', 12) FROM messages "
                "WHERE messages MATCH ? ORDER BY rank LIMIT ?", (match, limit)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [{"chat_id": r[0], "session": r[1], "role": r[2], "text": r[3],
                 "ts": r[4], "snippet": r[5]} for r in rows]

    def close(self) -> None:
        self.conn.close()


def search_sessions(home, query: str, limit: int = 10) -> list[dict]:
    """Conveniência: reindexa (incremental) e busca. Fail-open → []."""
    try:
        idx = SessionIndex(home)
        idx.reindex()
        out = idx.search(query, limit)
        idx.close()
        return out
    except Exception:  # noqa: BLE001 — busca de sessão nunca derruba o turno
        return []
