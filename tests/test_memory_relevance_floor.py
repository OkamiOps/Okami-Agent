"""Paridade Hermes (min_trust): recall com query tem PISO de relevância. Sem ele, o recall sempre unia
os 20 itens mais recentes como candidatos e devolvia top-N MESMO sem casar nada (rec/imp sempre > 0,
_minmax forçava o melhor a 1.0) → injetava memória irrelevante TODO turno → o modelo ancorava em fato
errado ('como você mencionou…') e se confundia. Agora item sem sinal real de relevância NÃO volta."""
from __future__ import annotations

from okami.memory import MemoryItem
from okami.memory.sqlite_fts5 import SqliteFTS5Memory


def test_recall_drops_irrelevant_recency_noise(tmp_path):
    m = SqliteFTS5Memory(tmp_path / "m.db")               # só FTS (sem embedder) — rel = score BM25
    m.write(MemoryItem(text="o projeto usa Python 3.12", kind="fact"))
    m.write(MemoryItem(text="o usuário gosta de café forte", kind="fact"))
    m.write(MemoryItem(text="a reunião é às 14h de quinta", kind="fact"))
    hits = m.recall("qual a linguagem do projeto?", limit=5)
    texts = " | ".join(h.text for h in hits)
    assert "Python" in texts                              # o RELEVANTE volta (casa 'projeto')
    assert "café" not in texts                            # irrelevante NÃO volta (mesmo recente)
    assert "reunião" not in texts
    m.close()


def test_recall_returns_empty_when_nothing_relevant(tmp_path):
    m = SqliteFTS5Memory(tmp_path / "m.db")
    m.write(MemoryItem(text="o usuário gosta de café", kind="fact"))
    m.write(MemoryItem(text="a senha do wifi mudou", kind="fact"))
    hits = m.recall("qual o resultado do jogo de futebol ontem?", limit=5)
    assert hits == []                                     # nada casa → injeta NADA (Hermes permite vazio)
    m.close()


def test_recall_still_returns_relevant_match(tmp_path):
    m = SqliteFTS5Memory(tmp_path / "m.db")
    m.write(MemoryItem(text="o deploy usa Vercel e Cloudflare", kind="fact"))
    hits = m.recall("onde fica o deploy?", limit=5)
    assert any("Vercel" in h.text for h in hits)          # match real continua voltando
    m.close()
