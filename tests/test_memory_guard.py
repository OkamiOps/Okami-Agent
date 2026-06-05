"""Memória: segredo NÃO persiste (P1) + health do Honcho (P2) + save_messages (P2) + list layered (P2).

Os 'segredos' aqui são fake (testam o filtro). Marcados p/ o secret-scan não falar (# pragma).
"""

from __future__ import annotations

from okami.memory import MemoryItem, open_memory, save_turn
from okami.memory import files
from okami.memory.honcho_backend import HonchoMemory
from okami.memory.policy import prepare

_SK = "sk-" + "livekey1234567890abcd"          # vetor fake montado em runtime (não vira literal no source)
_AKIA = "AKIA" + "IOSFODNN7EXAMPLE"


# ----------------------------------------------------------------- P1: segredo não vira memória
def test_prepare_refuses_secret():
    assert prepare(f"minha chave é {_SK}", source="agent") is None
    assert prepare(f"OPENAI_API_KEY={_SK}", source="cli", force=True) is None   # nem com force


def test_prepare_keeps_normal_fact():
    item = prepare("o usuário prefere Python e testes com pytest", source="agent")
    assert item is not None and "Python" in item.text


def test_append_user_refuses_secret(tmp_path):
    assert files.append_user(tmp_path, f"a chave é {_SK}") is False
    assert not (tmp_path / "USER.md").exists()
    assert files.append_user(tmp_path, "prefere respostas curtas e diretas") is True


def test_remember_user_tool_refuses_secret(tmp_path):
    from okami.core.tools import RememberUser, ToolContext
    out = RememberUser().run({"text": f"minha senha de prod é {_AKIA}"}, ToolContext(workspace=tmp_path))
    assert out.effect is False and "segredo" in out.output.lower()


def test_remember_tool_does_not_persist_secret(tmp_path):
    from okami.core.tools import RememberFact, ToolContext
    m = open_memory(tmp_path, backend="sqlite-fts5")
    RememberFact().run({"text": f"guarde isto: {_AKIA}"}, ToolContext(workspace=tmp_path, memory=m))
    assert m.count() == 0                       # segredo não foi para o sqlite
    m.close()


def test_direct_backend_write_skips_secret(tmp_path):
    """#P1: write() DIRETO (compaction/learning não passam por prepare) também é bloqueado."""
    m = open_memory(tmp_path, backend="sqlite-fts5")
    m.write(MemoryItem(text=f"[user] o token é {_SK}", kind="turn", source="user"))   # estilo compaction
    assert m.count() == 0
    m.write(MemoryItem(text="fato normal sem segredo nenhum", kind="fact"))
    assert m.count() == 1                       # não-segredo passa
    m.close()


def test_holographic_backend_write_skips_secret(tmp_path):
    m = open_memory(tmp_path, backend="holographic")
    m.write(MemoryItem(text=f"chave de deploy {_AKIA}", kind="lesson"))
    assert m.count() == 0
    m.close()


def test_honcho_write_skips_secret():
    from tests.test_layered_honcho import FakeHonchoClient
    m = HonchoMemory(client=FakeHonchoClient())
    m.write(MemoryItem(text=f"o segredo é {_SK}", source="user"))
    assert m.count() == 0                       # add_messages nem foi chamado


def test_is_secret_item_helper():
    from okami.memory.base import is_secret_item
    assert is_secret_item(MemoryItem(text=f"x {_SK}")) is True
    assert is_secret_item(MemoryItem(text="texto comum")) is False
    assert is_secret_item(f"raw {_AKIA}") is True   # aceita str crua também


# ----------------------------------------------------------------- P2: Honcho nunca volta ao self-model
def test_honcho_old_sdk_never_asks_self_model():
    """#P2: SDK antigo (chat só aceita query) → NUNCA chama assistant.chat sem target; cai p/ user.chat."""
    class _OldPeer:
        def __init__(self, pid):
            self.id, self.calls = pid, []

        def message(self, t):
            return t

        def chat(self, query):                  # SÓ query — sem target/session/reasoning
            self.calls.append(query)
            return f"resposta-de-{self.id}"

    class _OldSession:
        def add_peers(self, p):
            pass

        def add_messages(self, m):
            pass

        def messages(self):
            return []

        def context(self, **k):
            raise TypeError("old sdk sem kwargs")

    class _OldClient:
        def __init__(self):
            self._s, self._p = _OldSession(), {}

        def peer(self, pid):
            return self._p.setdefault(pid, _OldPeer(pid))

        def session(self, sid):
            return self._s

    m = HonchoMemory(client=_OldClient())
    hits = m.recall("quem é o usuário?")
    assert m.assistant.calls == []              # assistant NUNCA chamado (todas as tentativas tinham target → TypeError)
    assert m.user.calls == ["quem é o usuário?"]   # caiu p/ user.chat global (correto, não self-model)
    assert hits and "resposta-de-user" in hits[0].text


# ----------------------------------------------------------------- P2: save_messages explícito
def test_save_turn_off_by_default(tmp_path):
    m = open_memory(tmp_path, backend="sqlite-fts5")
    assert save_turn(m, "oi, tudo bem com você?", source="user", cfg_memory={}) is False
    assert m.count() == 0                       # default OFF — conversa não vira memória sozinha
    m.close()


def test_save_turn_on_writes(tmp_path):
    m = open_memory(tmp_path, backend="sqlite-fts5")
    assert save_turn(m, "implementar login com OAuth no backend", source="user",
                     cfg_memory={"save_messages": True}) is True
    assert m.count() == 1
    m.close()


def test_save_turn_skips_secret_even_when_on(tmp_path):
    m = open_memory(tmp_path, backend="sqlite-fts5")
    assert save_turn(m, f"o token de deploy é {_SK}", source="user",
                     cfg_memory={"save_messages": True}) is False
    assert m.count() == 0
    m.close()


# ----------------------------------------------------------------- P2: health do Honcho
class _BoomSession:
    def add_peers(self, peers):
        pass

    def add_messages(self, msgs):
        raise RuntimeError("honcho down")

    def messages(self):
        raise RuntimeError("honcho down")

    def context(self, **k):
        raise RuntimeError("honcho down")


class _BoomPeer:
    def __init__(self, pid):
        self.id = pid

    def message(self, t):
        return t

    def chat(self, *a, **k):
        raise RuntimeError("honcho down")


class _BoomClient:
    def peer(self, pid):
        return _BoomPeer(pid)

    def session(self, sid):
        return _BoomSession()


def test_honcho_health_records_failures():
    m = HonchoMemory(client=_BoomClient(), required=True)
    m.write(MemoryItem(text="oi", source="user"))   # add_messages explode → registra
    m.recall("preferências")                          # chat explode → registra
    h = m.health()
    assert h["ok"] is False and h["failures"] >= 1
    assert "honcho down" in h["last_error"] and h["required"] is True


def test_healthy_honcho_reports_ok():
    from tests.test_layered_honcho import FakeHonchoClient
    m = HonchoMemory(client=FakeHonchoClient())
    m.write(MemoryItem(text="oi", source="user"))
    h = m.health()
    assert h["ok"] is True and h["failures"] == 0


# ----------------------------------------------------------------- P2: memory list layered não quebra
def test_memory_list_layered_no_crash(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: p\nproviders:\n  p:\n    tier: local\n    model: m\n"
        "memory:\n  backend: [sqlite-fts5, holographic]\n", encoding="utf-8")
    res = CliRunner().invoke(app, ["memory", "list", "-w", str(tmp_path / "ws")])
    assert res.exit_code == 0                         # antes: AttributeError 'LayeredMemory' has no 'fts'


def test_layered_health_aggregates(tmp_path):
    from okami.memory.layered import LayeredMemory
    a = open_memory(tmp_path / "a", backend="sqlite-fts5")
    boom = HonchoMemory(client=_BoomClient(), required=True)
    boom.write(MemoryItem(text="x", source="user"))   # gera falha
    layered = LayeredMemory([a, boom])
    h = layered.health()
    assert h["ok"] is False                            # camada required falhou
    assert any(lay.get("backend") == "honcho" and not lay["ok"] for lay in h["layers"])
    layered.close()
