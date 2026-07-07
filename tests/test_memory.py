"""Testes da memória (sqlite-fts5) + auto-compaction (§6)."""

from __future__ import annotations

import numpy as np

from okami.memory import MemoryItem, compaction, files, open_memory
from okami.memory.sqlite_fts5 import SqliteFTS5Memory


class FakeEmbedder:
    """Embedder determinístico p/ teste (vetores por palavra-chave)."""

    VOCAB = {"gato": [1, 0, 0], "felino": [0.95, 0.1, 0], "carro": [0, 1, 0], "python": [0, 0, 1]}

    def embed(self, texts):
        return [self._v(t) for t in texts]

    def embed_one(self, text):
        return self._v(text)

    def _v(self, text):
        v = np.zeros(3, dtype=float)
        for w, vec in self.VOCAB.items():
            if w in text.lower():
                v = v + np.array(vec, dtype=float)
        if not v.any():
            v = np.array([0.01, 0.01, 0.01])
        return v.tolist()


def test_write_and_recall_fts(tmp_path):
    m = open_memory(tmp_path)
    m.write(MemoryItem(text="o usuário prefere ShadCN para frontend", kind="fact"))
    m.write(MemoryItem(text="o deploy usa Vercel", kind="fact"))
    hits = m.recall("shadcn frontend", limit=5)
    assert any("ShadCN" in h.text for h in hits)
    assert m.count() == 2
    m.close()


def test_recall_empty_returns_recent(tmp_path):
    m = open_memory(tmp_path)
    for i in range(3):
        m.write(MemoryItem(text=f"fato {i}", kind="fact"))
    recent = m.recall("", limit=2)
    assert len(recent) == 2 and recent[0].text == "fato 2"  # mais novo primeiro
    m.close()


def test_inject_block(tmp_path):
    m = open_memory(tmp_path)
    m.write(MemoryItem(text="prefere TypeScript", kind="fact"))
    block = m.inject("typescript")
    assert "JÁ SABE" in block and "TypeScript" in block        # header de USO (não rótulo passivo)
    assert "não recite" in block.lower()                       # instrui ancorar sem recitar
    m.close()


def test_compaction_distills_durable_then_shortens(tmp_path):
    m = open_memory(tmp_path)
    messages = [{"role": "system", "content": "sys"}]
    for i in range(20):
        messages.append({"role": "assistant", "content": f"o usuário prefere a opção {i} no fluxo"})
    new_msgs, distilled = compaction.compact(messages, m, keep_tail=4)
    # encurtou: system + resumo + tail
    assert len(new_msgs) == 2 + 4
    assert distilled > 0
    # fato durável recuperável da memória; nota explica a separação de camadas
    assert m.recall("opção 1", limit=5)
    assert "DESTILADOS" in new_msgs[1]["content"]
    m.close()


def test_compaction_does_not_promote_raw_ephemeral_turns(tmp_path):
    # P2: progresso efêmero/log NÃO vira "fato" na memória semântica (fica só na sessão/transcript).
    m = open_memory(tmp_path)
    messages = [{"role": "system", "content": "sys"}]
    for i in range(20):
        messages.append({"role": "assistant", "content": "ok"})       # trivial/efêmero (<8 chars)
    new_msgs, distilled = compaction.compact(messages, m, keep_tail=4)
    assert len(new_msgs) == 2 + 4 and distilled == 0                   # encurtou mas NÃO poluiu a memória
    m.close()


def test_compaction_noop_when_small(tmp_path):
    m = open_memory(tmp_path)
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "oi"}]
    new_msgs, promoted = compaction.compact(messages, m, keep_tail=6)
    assert new_msgs == messages and promoted == 0
    m.close()


def test_hybrid_semantic_retrieval(tmp_path):
    # 'felino' não aparece em nenhum texto → só retrieval semântico acha o 'gato'.
    m = SqliteFTS5Memory(tmp_path / "m.db", embedder=FakeEmbedder())
    m.write(MemoryItem(text="tenho um gato em casa"))
    m.write(MemoryItem(text="comprei um carro novo"))
    m.write(MemoryItem(text="uso python no trabalho"))
    hits = m.recall("felino", limit=1)
    assert hits and "gato" in hits[0].text
    m.close()


def test_dedup_reinforces_instead_of_duplicating(tmp_path):
    m = SqliteFTS5Memory(tmp_path / "m.db", embedder=FakeEmbedder())
    id1 = m.write(MemoryItem(text="tenho um gato"))
    id2 = m.write(MemoryItem(text="tenho um gato"))  # idêntico → dedup
    assert id1 == id2 and m.count() == 1
    m.close()


def test_dedup_near_duplicate_without_embedder(tmp_path):
    """Sem embedder, dedup era só texto IDÊNTICO — um parafraseio virava item NOVO. Agora
    _find_duplicate cai no fallback jaccard (_content_tokens/_jaccard) e reforça o existente."""
    m = SqliteFTS5Memory(tmp_path / "m.db")  # sem embedder
    id1 = m.write(MemoryItem(text="o usuário prefere respostas curtas e diretas"))
    id2 = m.write(MemoryItem(text="o usuário prefere respostas diretas e curtas"))  # quase-idêntico
    assert id1 == id2 and m.count() == 1
    m.close()


def test_dedup_near_duplicate_respects_threshold(tmp_path):
    """Textos genuinamente diferentes (jaccard baixo) NÃO devem colidir — não é dedup agressivo demais."""
    m = SqliteFTS5Memory(tmp_path / "m.db")
    m.write(MemoryItem(text="o usuário prefere respostas curtas e diretas"))
    m.write(MemoryItem(text="o deploy roda em Vercel com Postgres"))
    assert m.count() == 2
    m.close()


def test_importance_heuristic_ranks_preferences(tmp_path):
    m = open_memory(tmp_path)  # sem embedder
    m.write(MemoryItem(text="o usuário sempre prefere modo escuro", kind="fact"))
    m.write(MemoryItem(text="abriu o app", kind="turn"))
    imp = {i.text: i.importance for i in m.recent(2)}
    assert imp["o usuário sempre prefere modo escuro"] > imp["abriu o app"]
    m.close()


def test_forget_supersedes_low_value(tmp_path):
    m = open_memory(tmp_path)
    for i in range(10):
        m.write(MemoryItem(text=f"item turno {i}", kind="turn"))
    removed = m.forget(max_items=4)
    assert removed == 6 and m.count() == 4
    m.close()


def test_keyword_fallback_bm25_no_embedder(tmp_path):
    # Sem embeddings: BM25 deve achar o item certo por keyword.
    m = open_memory(tmp_path)
    m.write(MemoryItem(text="o deploy do frontend usa Vercel"))
    m.write(MemoryItem(text="o banco de dados e Postgres"))
    m.write(MemoryItem(text="os testes rodam com pytest"))
    hits = m.recall("frontend vercel", limit=1)
    assert hits and "Vercel" in hits[0].text
    m.close()


def test_accent_insensitive_recall(tmp_path):
    m = open_memory(tmp_path)
    m.write(MemoryItem(text="uso programação assíncrona no projeto"))
    m.write(MemoryItem(text="gosto de café pela manhã"))
    hits = m.recall("programacao", limit=1)  # query SEM acento
    assert hits and "programa" in hits[0].text.lower()
    m.close()


def test_embedder_circuit_breaker_degrades(tmp_path):
    from okami.memory.sqlite_fts5 import SqliteFTS5Memory as _M

    class BadEmbedder:
        def embed(self, texts):
            raise RuntimeError("offline")

        def embed_one(self, text):
            raise RuntimeError("offline")

    m = _M(tmp_path / "m.db", embedder=BadEmbedder())
    m.write(MemoryItem(text="o usuário gosta de café"))  # embed falha → grava sem vetor
    hits = m.recall("café", limit=1)  # keyword (BM25) ainda funciona
    assert hits and "café" in hits[0].text
    m.close()


def test_files_append_fact(tmp_path):
    files.append_fact(tmp_path, "decisão: usar Python")
    files.append_fact(tmp_path, "decisão: usar Python")  # dedup
    content = files.read_memory_md(tmp_path)
    assert content.count("decisão: usar Python") == 1
