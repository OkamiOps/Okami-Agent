"""Testes da memória em camadas (LayeredMemory) e do backend Honcho (SDK mockado)."""

from __future__ import annotations

from okami.memory import MemoryItem, open_memory
from okami.memory.honcho_backend import HonchoMemory
from okami.memory.layered import LayeredMemory


# ----------------------------------------------------------------- LayeredMemory
def test_layered_fanout_and_merge(tmp_path):
    a = open_memory(tmp_path / "a", backend="sqlite-fts5")
    b = open_memory(tmp_path / "b", backend="holographic")
    layered = LayeredMemory([a, b])
    layered.write(MemoryItem(text="o deploy usa Vercel no frontend"))
    layered.write(MemoryItem(text="os testes rodam com pytest"))
    hits = layered.recall("frontend vercel", limit=5)
    assert any("Vercel" in h.text for h in hits)
    # dedup: o mesmo fato nos dois backends não duplica no recall
    texts = [h.text for h in hits]
    assert len(texts) == len(set(texts))
    assert layered.count() >= 2
    layered.close()


def test_layered_inject_concatenates(tmp_path):
    a = open_memory(tmp_path / "a", backend="sqlite-fts5")
    a.write(MemoryItem(text="usuário prefere Python", kind="fact"))

    class Stub:
        def inject(self, query="", limit=5):
            return "BLOCO B"
        def recall(self, q, limit=5):
            return []
        def recent(self, limit=10):
            return []
        def write(self, item):
            return 0
        def count(self):
            return 0

    layered = LayeredMemory([a, Stub()])
    block = layered.inject("python")
    assert "Python" in block and "BLOCO B" in block
    layered.close()


def test_open_memory_list_builds_layered(tmp_path):
    m = open_memory(tmp_path, backend=["sqlite-fts5", "holographic"])
    assert isinstance(m, LayeredMemory) and len(m.backends) == 2
    m.close()


# ----------------------------------------------------------------- Honcho (mock)
class FakePeer:
    def __init__(self, pid):
        self.id = pid

    def message(self, text):
        return {"peer": self.id, "text": text}

    def chat(self, query):  # API dialética (oráculo)
        return f"insight sobre '{query}': o usuário prefere modo escuro"


class FakeSession:
    def __init__(self):
        self.msgs = []

    def add_peers(self, peers):
        pass

    def add_messages(self, msgs):
        self.msgs.extend(msgs)

    def context(self):
        return "user-model: gosta de respostas diretas"

    def messages(self):
        return self.msgs


class FakeHonchoClient:
    def __init__(self):
        self._session = FakeSession()

    def peer(self, pid):
        return FakePeer(pid)

    def session(self, sid):
        return self._session


def test_honcho_write_recall_inject_mocked():
    m = HonchoMemory(client=FakeHonchoClient())
    m.write(MemoryItem(text="oi Honcho", source="user"))
    assert m.count() == 1                       # add_messages chamado
    hits = m.recall("preferências")             # dialética → insight sintetizado
    assert hits and "modo escuro" in hits[0].text and hits[0].kind == "summary"
    block = m.inject("preferências")            # camada base (context) + dialética SEMPRE-ON (pessoa+tarefa)
    assert "user-model" in block                # session.context() (camada base)
    assert "modo escuro" in block               # dialética disparou no nível da pessoa, não só da tarefa
    assert "recite" in block.lower()            # header de USO ("não recite"), não rótulo passivo
