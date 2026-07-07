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


def test_layered_inject_single_preamble_and_capped():
    """Antes: cada backend contribuía o BLOCO INTEIRO (preâmbulo próprio) → N preâmbulos + 2x volume
    pro mesmo conteúdo. Agora: UM preâmbulo (do 1º backend com header) + itens deduplicados, capados."""

    class StubA:
        def inject(self, query="", limit=5):
            return "HEADER A\n- fato um\n- fato dois\n- fato três"
        def recall(self, q, limit=5):
            return []
        def recent(self, limit=10):
            return []
        def write(self, item):
            return 0
        def count(self):
            return 0

    class StubB:
        """Traz a MESMA linha ('- fato um') que StubA já injetou — camadas sabendo a mesma coisa."""
        def inject(self, query="", limit=5):
            return "HEADER B\n- fato um\n- fato quatro"
        def recall(self, q, limit=5):
            return []
        def recent(self, limit=10):
            return []
        def write(self, item):
            return 0
        def count(self):
            return 0

    layered = LayeredMemory([StubA(), StubB()])
    block = layered.inject("query", limit=3)
    lines = block.splitlines()
    assert lines[0] == "HEADER A"                        # só o header do 1º backend (não HEADER B também)
    assert lines.count("HEADER B") == 0
    assert lines.count("- fato um") == 1                 # duplicata entre backends não repete
    assert len(lines) <= 1 + 3                            # preâmbulo + no máximo `limit` itens


def test_open_memory_list_builds_layered(tmp_path):
    m = open_memory(tmp_path, backend=["sqlite-fts5", "holographic"])
    assert isinstance(m, LayeredMemory) and len(m.backends) == 2
    m.close()


# ----------------------------------------------------------------- Honcho (mock)
class FakePeer:
    def __init__(self, pid):
        self.id = pid
        self.calls = []                         # registra (query, target, reasoning_level)

    def message(self, text):
        return {"peer": self.id, "text": text}

    def chat(self, query, *, target=None, session=None, reasoning_level=None):
        self.calls.append({"q": query, "target": getattr(target, "id", target), "rl": reasoning_level})
        return f"insight sobre '{query}': o usuário prefere modo escuro"


class FakeSession:
    def __init__(self):
        self.msgs = []
        self.ctx_calls = []                     # registra peer_target/peer_perspective/search_query

    def add_peers(self, peers):
        pass

    def add_messages(self, msgs):
        self.msgs.extend(msgs)

    def context(self, *, peer_target=None, peer_perspective=None, search_query=None):
        self.ctx_calls.append({"peer_target": peer_target, "peer_perspective": peer_perspective,
                               "search_query": search_query})
        return "user-model: gosta de respostas diretas"

    def messages(self):
        return self.msgs


class FakeHonchoClient:
    def __init__(self):
        self._session = FakeSession()
        self._peers = {}

    def peer(self, pid):
        return self._peers.setdefault(pid, FakePeer(pid))

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


def test_honcho_dialectic_targets_user_not_self():
    """P0: a dialética pergunta SOBRE O USUÁRIO (assistant.chat target=user), não sobre a própria Okami."""
    m = HonchoMemory(client=FakeHonchoClient())
    m.recall("preferências")
    assert m.assistant.calls, "assistant.chat não foi chamado"
    assert m.assistant.calls[0]["target"] == m.user.id   # target = user (não vazio → não é self-model)
    assert m.assistant.calls[0]["rl"] == "low"           # reasoning_level passado
    # bug antigo: assistant.chat(query) SEM target → perguntava sobre a Okami. Agora nunca.
    assert all(c["target"] == m.user.id for c in m.assistant.calls)


def test_honcho_inject_passes_peer_target():
    """P1: session.context recebe peer_target=user (perspectiva da Okami) — caminho do card do usuário."""
    m = HonchoMemory(client=FakeHonchoClient())
    m.inject("preferências")
    assert m.session.ctx_calls, "session.context não foi chamado"
    c0 = m.session.ctx_calls[0]
    assert c0["peer_target"] == m.user.id and c0["peer_perspective"] == m.assistant.id


def test_honcho_user_fallback_when_assistant_silent():
    """Se a Okami ainda não sabe nada (assistant retorna vazio), cai na rep. global do próprio user."""
    client = FakeHonchoClient()
    m = HonchoMemory(client=client)
    m.assistant.chat = lambda *a, **k: ""        # assistant sem insight
    hits = m.recall("preferências")
    assert hits and "modo escuro" in hits[0].text   # veio de user.chat (fallback)
    assert m.user.calls and m.user.calls[0]["target"] is None   # user.chat global (sem target)


def test_honcho_inject_serves_cache_without_network_on_second_call():
    """P0 latência: inject() fazia até 3 chamadas SÍNCRONAS de dialética (LLM remoto) TODO turno.
    Porta o prefetch do Hermes: 1ª chamada por query é síncrona (popula cache); a 2ª, dentro do TTL,
    serve do cache SEM tocar peer.chat/session.context de novo."""
    client = FakeHonchoClient()
    m = HonchoMemory(client=client)
    block1 = m.inject("preferências")
    calls_after_first = len(m.assistant.calls) + len(m.session.ctx_calls)
    assert calls_after_first > 0                         # 1ª vez: rede/LLM tocado de verdade
    block2 = m.inject("preferências")                    # 2ª vez, mesma query, dentro do TTL
    assert block2 == block1
    assert len(m.assistant.calls) + len(m.session.ctx_calls) == calls_after_first  # SEM chamada nova


def test_honcho_inject_cache_expands_ttl_triggers_background_refresh(monkeypatch):
    """Cache vencido: ainda serve o valor cacheado NA HORA (não bloqueia o turno atual), mas dispara
    um refresh em background que, ao terminar, atualiza o cache p/ a PRÓXIMA chamada."""
    client = FakeHonchoClient()
    m = HonchoMemory(client=client)
    m.inject("preferências")                             # popula cache
    m._inject_ttl = -1.0                                 # força "vencido" sem esperar de verdade
    block = m.inject("preferências")                     # serve do cache velho, dispara refresh assíncrono
    assert block                                          # não voltou vazio (serviu do cache)
    # espera o refresh em background terminar (thread daemon, curta — mock é síncrono/instantâneo)
    import time as _t
    for _ in range(50):
        with m._inject_lock:
            if "preferências" not in m._inject_inflight:
                break
        _t.sleep(0.01)
    with m._inject_lock:
        assert "preferências" not in m._inject_inflight   # refresh concluiu, não ficou "em voo" p/ sempre


# ----------------------------------------------------------------- config do Honcho (P1)
def _capture_honcho(monkeypatch):
    captured = {}

    class FakeHM:
        def __init__(self, **kw):
            captured.update(kw)

        def close(self):
            pass

    monkeypatch.setattr("okami.memory.honcho_backend.HonchoMemory", FakeHM)
    return captured


def test_honcho_config_workspace_id_and_api_key_env(tmp_path, monkeypatch):
    cap = _capture_honcho(monkeypatch)
    monkeypatch.setenv("HONCHO_API_KEY", "secret-xyz")
    monkeypatch.setenv("HONCHO_BASE_URL", "https://honcho.example/v1")
    cfg = {"honcho": {"base_url": "${HONCHO_BASE_URL}", "api_key_env": "HONCHO_API_KEY",
                      "workspace_id": "ws-id", "session": "s1"}}
    open_memory(tmp_path, backend="honcho", config=cfg)
    assert cap["workspace"] == "ws-id"                       # workspace_id (nome do SDK), não 'okami'
    assert cap["api_key"] == "secret-xyz"                    # resolvido de api_key_env
    assert cap["base_url"] == "https://honcho.example/v1"    # ${ENV} expandido no base_url


def test_honcho_config_literal_env_ref_resolved(tmp_path, monkeypatch):
    cap = _capture_honcho(monkeypatch)
    monkeypatch.setenv("HONCHO_API_KEY", "live-key")
    open_memory(tmp_path, backend="honcho", config={"honcho": {"api_key": "${HONCHO_API_KEY}", "workspace": "ws"}})
    assert cap["api_key"] == "live-key"                      # NÃO o literal "${HONCHO_API_KEY}"


def test_honcho_config_undefined_env_is_none(tmp_path, monkeypatch):
    cap = _capture_honcho(monkeypatch)
    monkeypatch.delenv("HONCHO_API_KEY", raising=False)
    open_memory(tmp_path, backend="honcho", config={"honcho": {"api_key": "${HONCHO_API_KEY}"}})
    assert cap["api_key"] is None                            # indefinido → None (nunca o literal)
