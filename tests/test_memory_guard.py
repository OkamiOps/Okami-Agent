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
