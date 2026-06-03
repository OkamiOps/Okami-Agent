"""Backend de memória híbrido: SQLite + FTS5 + embeddings + recência + importância.

Retrieval funde 3 sinais (estado da arte — Generative Agents + Mem0 + práticas 2026):
  score = w_rel·relevância + w_rec·recência + w_imp·importância   (cada um normalizado [0,1])
- relevância = semântica (cosine de embeddings, se houver embedder) + keyword (FTS/overlap).
- recência   = decay exponencial sobre o último acesso (reforço de uso).
- importância = heurística por tipo/conteúdo (hook p/ LLM no futuro).

Write faz DEDUP (ADD/NOOP estilo Mem0): se já existe item muito similar, reforça em vez de
duplicar. `forget()` esquece os de menor valor (anti context-rot). Embedder é OPCIONAL: sem
ele, degrada para keyword + recência + importância. Escopo por workspace.
"""

from __future__ import annotations

import re
import sqlite3
import time
import unicodedata
from pathlib import Path

import numpy as np

from okami.memory.base import Memory, MemoryItem
from okami.memory.embeddings import Embedder, cosine, from_blob, to_blob

_WORD = re.compile(r"\w+", re.UNICODE)


def _fold(s: str) -> str:
    """lowercase + remove acentos (PT): 'Programação' -> 'programacao'."""
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower())
                   if not unicodedata.combining(c))
_IMPORTANT_HINTS = ("prefere", "sempre", "nunca", "decid", "importante", "regra",
                    "credenc", "senha", "objetivo", "não use", "deve ", "obrigat")


def _heuristic_importance(item: MemoryItem) -> float:
    base = {"decision": 0.8, "summary": 0.7, "fact": 0.55, "procedural": 0.75,
            "turn": 0.3}.get(item.kind, 0.5)
    t = item.text.lower()
    if any(h in t for h in _IMPORTANT_HINTS):
        base = min(1.0, base + 0.2)
    return base


def _term_overlap(query: str, text: str) -> float:
    qt = set(_fold(w) for w in _WORD.findall(query))
    if not qt:
        return 0.0
    tt = set(_fold(w) for w in _WORD.findall(text))
    return len(qt & tt) / len(qt)


def _minmax(vals: list[float]) -> list[float]:
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return [1.0 if hi > 1e-9 else 0.0] * len(vals)
    return [(v - lo) / (hi - lo) for v in vals]


_COLS = "id, text, kind, source, ts, importance, last_access, access_count, embedding"


class SqliteFTS5Memory(Memory):
    def __init__(self, path: Path, clock=time.time, embedder: Embedder | None = None,
                 weights: tuple[float, float, float] = (1.5, 0.5, 1.0),
                 dedup_threshold: float = 0.93, decay_per_hour: float = 0.99):
        self.path = Path(path)
        self.clock = clock
        self.embedder = embedder
        self.w_rel, self.w_rec, self.w_imp = weights
        self.dedup_threshold = dedup_threshold
        self.decay_per_hour = decay_per_hour
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("PRAGMA journal_mode=WAL")     # leitura rápida concorrente (como o Hermes)
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.fts = self._init_schema()
        # cache da matriz de embeddings (cosine vetorizado, sem loop Python por linha)
        self._mat = None
        self._mat_ids: list[int] = []
        self._mat_dirty = True

    def _init_schema(self) -> bool:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS items("
            "id INTEGER PRIMARY KEY, text TEXT, kind TEXT, source TEXT, tags TEXT, ts REAL, "
            "importance REAL DEFAULT 0.5, last_access REAL DEFAULT 0, access_count INTEGER DEFAULT 0, "
            "embedding BLOB, superseded INTEGER DEFAULT 0)"
        )
        try:
            self.conn.executescript(
                "CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5("
                "text, content='items', content_rowid='id', tokenize='unicode61 remove_diacritics 2');"
                "CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN"
                "  INSERT INTO items_fts(rowid, text) VALUES (new.id, new.text); END;"
                "CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN"
                "  INSERT INTO items_fts(items_fts, rowid, text) VALUES('delete', old.id, old.text); END;"
                "CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN"
                "  INSERT INTO items_fts(items_fts, rowid, text) VALUES('delete', old.id, old.text);"
                "  INSERT INTO items_fts(rowid, text) VALUES (new.id, new.text); END;"
            )
            self.conn.commit()
            return True
        except sqlite3.OperationalError:
            self.conn.commit()
            return False

    # ------------------------------------------------------------------ write
    def write(self, item: MemoryItem) -> int:
        ts = item.ts or self.clock()
        importance = item.importance if item.importance is not None else _heuristic_importance(item)
        emb = None
        if self.embedder is not None:
            try:
                emb = self.embedder.embed_one(item.text)
            except Exception:  # noqa: BLE001 — embedder offline → segue sem semântica
                emb = None

        dup_id = self._find_duplicate(item.text, emb)
        if dup_id is not None:
            self.conn.execute(
                "UPDATE items SET access_count = access_count + 1, "
                "importance = max(importance, ?), last_access = ? WHERE id = ?",
                (importance, ts, dup_id),
            )
            self.conn.commit()
            return dup_id

        cur = self.conn.execute(
            "INSERT INTO items(text, kind, source, tags, ts, importance, last_access, access_count, embedding) "
            "VALUES (?,?,?,?,?,?,?,0,?)",
            (item.text, item.kind, item.source, item.tags, ts, importance, ts,
             to_blob(emb) if emb is not None else None),
        )
        self.conn.commit()
        if emb is not None:
            self._mat_dirty = True
        return int(cur.lastrowid)

    def _find_duplicate(self, text: str, emb) -> int | None:
        if emb is not None:
            for rid, _t, _k, _s, _ts, _imp, _la, _ac, blob in self._load():
                if blob is not None and cosine(emb, from_blob(blob)) >= self.dedup_threshold:
                    return rid
            return None
        row = self.conn.execute(
            "SELECT id FROM items WHERE text = ? AND superseded = 0", (text,)
        ).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------------ read
    def _load(self) -> list[tuple]:
        return self.conn.execute(
            f"SELECT {_COLS} FROM items WHERE superseded = 0"
        ).fetchall()

    def _item(self, row: tuple, score: float | None = None) -> MemoryItem:
        return MemoryItem(text=row[1], kind=row[2], source=row[3], ts=row[4],
                          importance=row[5], last_access=row[6], access_count=row[7],
                          id=row[0], score=score)

    def _keyword_scores(self, query: str) -> dict[int, float]:
        """BM25 do FTS5 (ranking de verdade) normalizado [0,1] por rowid. {} se sem FTS."""
        if not self.fts:
            return {}
        terms = _WORD.findall(query.lower())
        if not terms:
            return {}
        match = " OR ".join(terms)
        try:
            rows = self.conn.execute(
                "SELECT rowid, bm25(items_fts) FROM items_fts WHERE items_fts MATCH ? "
                "ORDER BY bm25(items_fts) LIMIT 200",
                (match,),
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        if not rows:
            return {}
        scores = {rid: -float(b) for rid, b in rows}  # bm25 menor = melhor → inverte
        vals = list(scores.values())
        lo, hi = min(vals), max(vals)
        if hi - lo < 1e-9:
            return {rid: 1.0 for rid in scores}
        return {rid: (v - lo) / (hi - lo) for rid, v in scores.items()}

    def _ensure_matrix(self) -> None:
        if not self._mat_dirty and self._mat is not None:
            return
        rows = self.conn.execute(
            "SELECT id, embedding FROM items WHERE superseded = 0 AND embedding IS NOT NULL"
        ).fetchall()
        self._mat_dirty = False
        if not rows:
            self._mat, self._mat_ids = None, []
            return
        ids, vecs = [], []
        for rid, blob in rows:
            ids.append(rid)
            vecs.append(from_blob(blob))
        mat = np.nan_to_num(np.vstack(vecs).astype(np.float32))
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._mat = mat / norms          # linhas normalizadas → cosine vira só matmul
        self._mat_ids = ids

    def _semantic_scores(self, query: str, topk: int = 50) -> dict[int, float]:
        """Top-k por cosine, vetorizado (um matmul). {} se sem embedder/offline."""
        if self.embedder is None:
            return {}
        try:
            q = self.embedder.embed_one(query)
        except Exception:  # noqa: BLE001 — circuit breaker já desabilitou
            return {}
        self._ensure_matrix()
        if self._mat is None:
            return {}
        qn = np.asarray(q, dtype=np.float32)
        n = float(np.linalg.norm(qn))
        if n == 0.0:
            return {}
        sims = self._mat @ (qn / n)
        idx = np.argsort(-sims)[:topk]
        return {self._mat_ids[i]: float(max(0.0, sims[i])) for i in idx}

    def _load_ids(self, ids) -> list[tuple]:
        marks = ",".join("?" * len(ids))
        return self.conn.execute(
            f"SELECT {_COLS} FROM items WHERE superseded = 0 AND id IN ({marks})", tuple(ids)
        ).fetchall()

    def recall(self, query: str, limit: int = 5) -> list[MemoryItem]:
        if not query.strip():
            return self.recent(limit)
        now = self.clock()
        # 1) candidatos RÁPIDOS: BM25 (FTS5, sub-ms) + semântico top-k (matmul) + recentes.
        kw = self._keyword_scores(query)
        sem = self._semantic_scores(query)
        cand = set(kw) | set(sem)
        cand.update(r[0] for r in self.conn.execute(
            "SELECT id FROM items WHERE superseded = 0 ORDER BY id DESC LIMIT 20"))
        if not cand:
            return []
        # 2) rerank só os candidatos (não a base inteira).
        rows = self._load_ids(cand)
        rel, rec, imp = [], [], []
        for row in rows:
            kws = kw.get(row[0], 0.0)
            sms = sem.get(row[0], 0.0)
            rel.append(0.75 * sms + 0.25 * kws if self.embedder is not None else kws)
            hours = max(0.0, (now - (row[6] or row[4])) / 3600.0)
            rec.append(self.decay_per_hour ** hours)
            imp.append(row[5] or 0.5)
        rel_n = _minmax(rel)  # min-max só na relevância; recência/importância cruas
        scored = [(self.w_rel * rel_n[i] + self.w_rec * rec[i] + self.w_imp * imp[i], rows[i])
                  for i in range(len(rows))]
        scored.sort(key=lambda x: -x[0])
        top = scored[:limit]
        self._bump([r[0] for _s, r in top], now)
        return [self._item(r, score=s) for s, r in top]

    def recent(self, limit: int = 10) -> list[MemoryItem]:
        rows = self.conn.execute(
            f"SELECT {_COLS} FROM items WHERE superseded = 0 ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._item(r) for r in rows]

    def _bump(self, ids: list[int], now: float) -> None:
        for rid in ids:
            self.conn.execute(
                "UPDATE items SET last_access = ?, access_count = access_count + 1 WHERE id = ?",
                (now, rid),
            )
        self.conn.commit()

    def count(self) -> int:
        return int(self.conn.execute("SELECT count(*) FROM items WHERE superseded = 0").fetchone()[0])

    # ------------------------------------------------------------------ forget (anti context-rot)
    def forget(self, max_items: int = 500) -> int:
        rows = self._load()
        if len(rows) <= max_items:
            return 0
        now = self.clock()
        scored = []
        for row in rows:
            hours = max(0.0, (now - (row[6] or row[4])) / 3600.0)
            recency = self.decay_per_hour ** hours
            value = 0.5 * (row[5] or 0.5) + 0.3 * recency + 0.2 * min(row[7], 5) / 5.0
            scored.append((value, row[0]))
        scored.sort(key=lambda x: x[0])  # menor valor primeiro
        remove = scored[: len(rows) - max_items]
        for _v, rid in remove:
            self.conn.execute("UPDATE items SET superseded = 1 WHERE id = ?", (rid,))
        self.conn.commit()
        self._mat_dirty = True
        return len(remove)

    def close(self) -> None:
        self.conn.close()
