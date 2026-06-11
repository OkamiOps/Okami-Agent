"""Fila de aprovação de escrita de memória (porta do write_approval do Hermes).

O review em BACKGROUND escreve memória sozinho — com `memory.write_approval: true`, essas
escritas ficam STAGED em .okami/pending/memory/ e você revisa pelo chat:
/memory pending | approve <id|all> | reject <id|all>. Escrita direta do usuário num turno
normal não muda (já passa pelos gates de policy).
"""
from __future__ import annotations

import tempfile

from okami.channels.base import Channel
from okami.core.tools.base import ToolContext
from okami.core.tools.memory import RememberFact, RememberUser
from okami.gateway import AgentEndpoint
from okami.memory.staging import PendingStore


# ── PendingStore ─────────────────────────────────────────────────────────────

def test_stage_list_roundtrip(tmp_path):
    st = PendingStore(tmp_path)
    pid = st.stage("fact", "decisão: usar Python", origin="review")
    items = st.pending()
    assert len(items) == 1
    assert items[0]["id"] == pid and items[0]["text"] == "decisão: usar Python"
    assert items[0]["kind"] == "fact" and items[0]["origin"] == "review"


def test_approve_applies_to_memory_md(tmp_path):
    st = PendingStore(tmp_path)
    st.stage("fact", "decisão: usar Python", origin="review")
    st.stage("user", "prefere respostas curtas", origin="review")
    applied = st.approve("all")
    assert applied == 2
    assert "decisão: usar Python" in (tmp_path / "MEMORY.md").read_text()
    assert "prefere respostas curtas" in (tmp_path / "USER.md").read_text()
    assert st.pending() == []                          # fila esvaziou


def test_approve_single_by_id(tmp_path):
    st = PendingStore(tmp_path)
    a = st.stage("fact", "fato A", origin="review")
    st.stage("fact", "fato B", origin="review")
    assert st.approve(a) == 1
    assert "fato A" in (tmp_path / "MEMORY.md").read_text()
    assert "fato B" not in (tmp_path / "MEMORY.md").read_text()
    assert len(st.pending()) == 1


def test_reject_discards(tmp_path):
    st = PendingStore(tmp_path)
    st.stage("fact", "lixo", origin="review")
    assert st.reject("all") == 1
    assert st.pending() == []
    assert not (tmp_path / "MEMORY.md").exists()


def test_pending_survives_restart(tmp_path):
    PendingStore(tmp_path).stage("fact", "durável", origin="review")
    assert len(PendingStore(tmp_path).pending()) == 1   # outra instância vê (arquivo, não RAM)


# ── tools em modo staging ────────────────────────────────────────────────────

class _Mem:
    def __init__(self):
        self.items = []

    def write(self, item):
        self.items.append(item)


def test_remember_staged_when_flagged(tmp_path):
    mem = _Mem()
    ctx = ToolContext(workspace=tmp_path, agent_home=tmp_path, memory=mem, stage_writes=True)
    r = RememberFact().run({"text": "decisão técnica: usar sqlite para a fila"}, ctx)
    assert r.ok and "aprovação" in r.output
    assert mem.items == []                              # NÃO escreveu direto
    assert len(PendingStore(tmp_path).pending()) == 1


def test_remember_user_staged_when_flagged(tmp_path):
    ctx = ToolContext(workspace=tmp_path, agent_home=tmp_path, stage_writes=True)
    r = RememberUser().run({"text": "prefere bullet points"}, ctx)
    assert r.ok
    assert not (tmp_path / "USER.md").exists()          # nada direto no USER.md
    assert PendingStore(tmp_path).pending()[0]["kind"] == "user"


def test_remember_direct_without_flag(tmp_path):
    mem = _Mem()
    ctx = ToolContext(workspace=tmp_path, agent_home=tmp_path, memory=mem)
    RememberFact().run({"text": "decisão técnica: usar sqlite na fila"}, ctx)
    assert mem.items                                    # comportamento normal preservado
    assert PendingStore(tmp_path).pending() == []


# ── /memory no chat ──────────────────────────────────────────────────────────

class FakeChannel(Channel):
    name = "fake"

    def __init__(self):
        self.sent = []

    def poll(self):
        return []

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def allowed(self, chat_id):
        return True


def _ep(home):
    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=FakeChannel(),
                         run_task=lambda *a, **k: None, spawn=lambda fn: fn(), agent_home=home)


def test_chat_memory_pending_and_approve(tmp_path):
    PendingStore(tmp_path).stage("fact", "fato do review", origin="review")
    ep = _ep(tmp_path)
    ep.handle("7", "/memory pending")
    assert any("fato do review" in t for _, t in ep.channel.sent)
    ep.handle("7", "/memory approve all")
    assert "fato do review" in (tmp_path / "MEMORY.md").read_text()
    ep.handle("7", "/memory pending")
    assert any("nada pendente" in t.lower() for _, t in ep.channel.sent)


def test_chat_memory_reject(tmp_path):
    PendingStore(tmp_path).stage("fact", "indesejado", origin="review")
    ep = _ep(tmp_path)
    ep.handle("7", "/memory reject all")
    assert PendingStore(tmp_path).pending() == []
    assert not (tmp_path / "MEMORY.md").exists()
