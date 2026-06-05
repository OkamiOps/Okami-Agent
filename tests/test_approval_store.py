"""Aprovação como objeto persistente single-use (#7): create/consume/expire + binding aos args."""

from __future__ import annotations

from okami.gateway.approvals import ApprovalStore


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def _store(tmp_path, clock):
    return ApprovalStore(tmp_path, clock=clock)


def _create(st, **over):
    base = dict(approval_id="abc123", tool="run_shell", args_hash="deadbeef", risk="high",
                category="destructive_shell", surface="telegram", chat_id="42", ttl=300.0)
    base.update(over)
    return st.create(**base)


def test_create_persists_object(tmp_path):
    clk = Clock()
    st = _store(tmp_path, clk)
    appr = _create(st)
    assert appr.approval_id == "abc123" and appr.used_at is None
    assert appr.expires_at == 1300.0 and appr.user_id == "42"   # user_id default = chat_id (DM)
    assert st.path.exists()                                     # gravou no disco


def test_consume_once_then_rejects(tmp_path):
    clk = Clock()
    st = _store(tmp_path, clk)
    _create(st)
    r1 = st.consume("abc123", "approved")
    assert r1.ok and r1.approval.decision == "approved"
    r2 = st.consume("abc123", "approved")                       # single-use
    assert not r2.ok and r2.reason == "já usado"


def test_single_use_survives_restart(tmp_path):
    clk = Clock()
    _store(tmp_path, clk)._append  # noqa: B018 — só p/ garantir o módulo
    st = _store(tmp_path, clk)
    _create(st)
    assert st.consume("abc123", "approved").ok
    st2 = ApprovalStore(tmp_path, clock=clk)                    # "reinicia o processo" → relê do disco
    assert not st2.consume("abc123", "approved").ok             # continua usado


def test_expiry_is_enforced(tmp_path):
    clk = Clock()
    st = _store(tmp_path, clk)
    _create(st, ttl=100.0)
    clk.t = 1000.0 + 101.0                                      # passou do prazo
    res = st.consume("abc123", "approved")
    assert not res.ok and res.reason == "expirado"


def test_args_hash_binding(tmp_path):
    clk = Clock()
    st = _store(tmp_path, clk)
    _create(st, args_hash="aaaa1111")
    bad = st.consume("abc123", "approved", args_hash="bbbb2222")
    assert not bad.ok and bad.reason == "args divergem"
    # mesmo id, hash certo → ok (mas só funciona porque o de cima NÃO marcou usado)
    ok = st.consume("abc123", "approved", args_hash="aaaa1111")
    assert ok.ok


def test_unknown_id(tmp_path):
    st = _store(tmp_path, Clock())
    assert st.consume("naoexiste", "approved").reason == "desconhecido"


def test_expire_if_pending(tmp_path):
    clk = Clock()
    st = _store(tmp_path, clk)
    _create(st)
    st.expire_if_pending("abc123")
    assert st.get("abc123").decision == "expired"
    assert not st.consume("abc123", "approved").ok             # expirado não consome
