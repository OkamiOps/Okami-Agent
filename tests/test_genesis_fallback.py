"""Fallback determinístico da gênese (okami/gateway/genesis.py `_GENESIS_MAX_TURNS`/`bump_genesis_turn`)
+ `/skip-setup` (okami/gateway/endpoint.py) — trava real de uso: modelo fraco em tool-calling (minimax)
nunca chama `finish_setup`, e sem isto o GENESIS_BLOCK reinjeta PRA SEMPRE (o bloco instrui "não mencione
isto ao usuário" → onboarding invisível sem saída)."""
from __future__ import annotations

import tempfile

from okami.channels.base import Channel
from okami.core import Task, TaskState
from okami.gateway import AgentEndpoint
from okami.gateway.genesis import (
    _GENESIS_MAX_TURNS,
    _genesis_turn_count,
    bump_genesis_turn,
    genesis_pending,
)


class FakeChannel(Channel):
    name = "fake"
    supports_media = False

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def poll(self):
        return []

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def allowed(self, chat_id):
        return True


def _runner_never_calls_finish_setup():
    """Simula um modelo fraco: SEMPRE termina COMPLETE sem jamais chamar finish_setup (não escreve
    genesis.done nem USER.md) — só assim o loop de gênese fica preso sem o fallback."""
    def _r(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, **kw):
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "tudo bem, seguindo em frente."
        return t
    return _r


def _ep(runner=None, ws=None, channel=None):
    ch = channel or FakeChannel()
    return AgentEndpoint("dev", cfg=None, ws=ws or tempfile.mkdtemp(), channel=ch,
                         run_task=runner or _runner_never_calls_finish_setup(),
                         approval_mode="manual", spawn=lambda fn: fn())


# ------------------------------------------------------------------ contador puro
def test_bump_genesis_turn_persists_and_increments(tmp_path):
    assert _genesis_turn_count(tmp_path) == 0
    assert bump_genesis_turn(tmp_path) == 1
    assert bump_genesis_turn(tmp_path) == 2
    assert _genesis_turn_count(tmp_path) == 2


def test_genesis_pending_true_before_max_turns(tmp_path):
    for _ in range(_GENESIS_MAX_TURNS - 1):
        bump_genesis_turn(tmp_path)
    assert genesis_pending(tmp_path) is True


def test_genesis_auto_seals_after_max_turns(tmp_path):
    for _ in range(_GENESIS_MAX_TURNS):
        bump_genesis_turn(tmp_path)
    assert genesis_pending(tmp_path) is False
    assert (tmp_path / ".okami" / "genesis.done").exists()


# ------------------------------------------------------------------ integração via AgentEndpoint._run
def test_genesis_block_stops_injecting_after_n_turns_without_finish_setup():
    ep = _ep()
    ws = ep.ws
    from okami.gateway.genesis import genesis_pending as _gp
    assert _gp(ws) is True
    for i in range(_GENESIS_MAX_TURNS + 2):        # manda bem mais turnos que o teto
        ep.handle("7", f"mensagem {i}")
    # depois do teto, a gênese deve estar selada — sem re-disparar em turnos futuros
    assert _gp(ws) is False
    assert (__import__("pathlib").Path(ws) / ".okami" / "genesis.done").exists()


def test_genesis_stops_injecting_block_into_extra_context():
    """Confirma que passado o teto, GENESIS_BLOCK não é mais prependado ao extra_context do run_task."""
    captured: list[str] = []

    def _r(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, **kw):
        captured.append(extra_context)
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok"
        return t

    ep = _ep(runner=_r)
    for i in range(_GENESIS_MAX_TURNS + 2):
        ep.handle("7", f"msg {i}")
    from okami.gateway.genesis import GENESIS_BLOCK
    assert GENESIS_BLOCK in captured[0]                          # primeiro turno: ainda pendente
    assert GENESIS_BLOCK not in captured[-1]                     # depois do fallback: já selado, para de injetar


# ------------------------------------------------------------------ /skip-setup
def test_skip_setup_seals_immediately():
    ch = FakeChannel()
    ep = _ep(channel=ch)
    ws = ep.ws
    from okami.gateway.genesis import genesis_pending as _gp
    assert _gp(ws) is True
    ep.handle("7", "/skip-setup")
    assert _gp(ws) is False
    assert (__import__("pathlib").Path(ws) / ".okami" / "genesis.done").exists()
    assert any("✅" in t for _, t in ch.sent)


def test_skip_setup_noop_when_already_sealed():
    ch = FakeChannel()
    ep = _ep(channel=ch)
    ep.handle("7", "/skip-setup")
    ch.sent.clear()
    ep.handle("7", "/skip-setup")            # 2ª vez: já selado
    assert any("already" in t.lower() or "nothing" in t.lower() for _, t in ch.sent)


def test_skip_setup_alias_finish_setup_also_seals():
    ep = _ep()
    ws = ep.ws
    ep.handle("7", "/finish-setup")
    from okami.gateway.genesis import genesis_pending as _gp
    assert _gp(ws) is False


# ------------------------------------------------------------------ já selado nunca re-dispara
def test_already_sealed_session_never_retriggers_genesis(tmp_path):
    (tmp_path / ".okami").mkdir(parents=True)
    (tmp_path / ".okami" / "genesis.done").write_text("done\n", encoding="utf-8")
    captured: list[str] = []

    def _r(cfg, ws, goal, *, approve=None, extra_context="", cancel=None, **kw):
        captured.append(extra_context)
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok"
        return t

    ep = _ep(runner=_r, ws=str(tmp_path))
    ep.handle("7", "oi")
    from okami.gateway.genesis import GENESIS_BLOCK
    assert GENESIS_BLOCK not in captured[0]
    assert _genesis_turn_count(tmp_path) == 0             # nunca contou turno de gênese (não estava pendente)
