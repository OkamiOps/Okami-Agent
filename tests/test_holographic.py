"""Testes da memória holográfica (HRR/VSA) — tudo local, sem rede."""

from __future__ import annotations

import numpy as np

from okami.memory import MemoryItem, open_memory
from okami.memory.holographic import HRREncoder


def test_encode_similarity_lexical():
    enc = HRREncoder(dim=512)
    a = enc.encode("deploy do frontend com Vercel")
    b = enc.encode("o frontend usa Vercel no deploy")   # tokens compartilhados → similar
    c = enc.encode("banco de dados Postgres e migrations")
    cos = lambda x, y: float(np.dot(x, y))  # já normalizados
    assert cos(a, b) > cos(a, c)


def test_encode_robust_to_accent_and_morphology():
    enc = HRREncoder(dim=512)
    a = enc.encode("programação assíncrona")
    b = enc.encode("programacao async program")  # sem acento + raiz compartilhada (trigramas)
    c = enc.encode("futebol e churrasco")
    assert float(np.dot(a, b)) > float(np.dot(a, c))


def test_bind_unbind_cleanup_roundtrip():
    enc = HRREncoder(dim=1024)
    role = enc._atom("role")
    value = enc._atom("engenheiro")
    bound = enc.bind(role, value)
    recovered = enc.unbind(role, bound)           # ≈ value (ruidoso)
    codebook = {"engenheiro": value, "medico": enc._atom("medico"), "advogado": enc._atom("advogado")}
    assert enc.cleanup(recovered, codebook) == "engenheiro"


def test_holographic_backend_recall_no_embedder_server(tmp_path):
    m = open_memory(tmp_path, backend="holographic")
    m.write(MemoryItem(text="o usuário prefere modo escuro na interface"))
    m.write(MemoryItem(text="o deploy roda no Vercel"))
    m.write(MemoryItem(text="os testes usam pytest"))
    hits = m.recall("interface modo escuro", limit=1)  # relevância via HRR local
    assert hits and "modo escuro" in hits[0].text
    m.close()
