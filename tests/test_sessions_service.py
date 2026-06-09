"""Session service: arquivar (/new) · listar (/sessions) · retomar (/resume) · exportar (/export)."""

from __future__ import annotations
import pytest

import itertools

from okami.gateway import AgentEndpoint
from okami.gateway.sessions import TranscriptStore


def test_store_archive_resume_export(tmp_path):
    clk = itertools.count(1000)
    st = TranscriptStore(tmp_path, clock=lambda: next(clk))
    st.append("c", "USER", "oi")
    st.append("c", "AGENTE", "olá")
    st.reset("c")                                    # /new → arquiva
    st.append("c", "USER", "conversa nova")
    arr = st.archives("c")
    assert len(arr) == 1 and arr[0]["turns"] == 1
    hist = st.resume("c", arr[0]["name"])            # retoma a arquivada
    assert ("USER", "oi") in hist and ("AGENTE", "olá") in hist
    out = st.export("c", tmp_path / "dump.md")
    assert out.exists() and "você" in out.read_text(encoding="utf-8")


class _Fake:
    name = "fake"

    def __init__(self):
        self.sent: list[str] = []

    def send(self, cid, text):
        self.sent.append(text)

    def send_audio(self, cid, p):
        pass

    def poll(self):
        return []

    def allowed(self, cid):
        return True


def test_session_commands_via_gateway(tmp_path):
    ch = _Fake()
    ep = AgentEndpoint("okami", None, tmp_path, ch, run_task=lambda *a, **k: None, spawn=lambda fn: fn())
    ep.store.append("c", "USER", "oi")
    ep.store.append("c", "AGENTE", "olá")
    ep.store.reset("c")
    ep.handle("c", "/sessions")
    assert "arquivadas" in ch.sent[-1]
    ep.handle("c", "/resume 1")
    assert "retomei" in ch.sent[-1] and ep.session("c").history          # carregou no histórico da sessão
    ep.handle("c", "/export")
    assert "exportado" in ch.sent[-1]


@pytest.fixture(autouse=True)
def _i18n_pt_locale():
    """i18n: estes testes foram escritos com as respostas do gateway em PT. Força o locale `pt` (o
    comportamento EN-default é coberto por test_i18n). Reseta após cada teste."""
    import okami.i18n as _i18n
    _i18n.set_lang("pt")
    yield
    _i18n.set_lang(None)
