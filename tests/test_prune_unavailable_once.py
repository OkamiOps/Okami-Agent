"""WIN #4: prune_unavailable (okami.core.tool_policy) avisava a MESMA tool indisponível em TODO
invocação (7 tools sem integração → ruído repetido a cada turno). Agora: cada tool só gera aviso
na PRIMEIRA vez que aparece neste processo, e o aviso sai como UMA linha-resumo (não uma por tool).
"""

from __future__ import annotations

from okami.core.tools import Tool
from okami.core.tool_policy import prune_unavailable, reset_unavailable_warnings


class _NeverReady(Tool):
    name = "never_ready_win4"
    description = "sempre indisponível"
    args_schema = {}

    def check(self):
        return "credencial ausente"


class _AlwaysOk(Tool):
    name = "always_ok_win4"
    description = "sempre disponível"
    args_schema = {}


def setup_function(_fn):
    reset_unavailable_warnings()


def test_first_call_emits_summary_once():
    msgs = []
    reg = {"never_ready_win4": _NeverReady(), "always_ok_win4": _AlwaysOk()}
    out = prune_unavailable(reg, emit=msgs.append)
    assert "never_ready_win4" not in out and "always_ok_win4" in out
    assert len(msgs) == 1
    assert "never_ready_win4" in msgs[0] and "credencial ausente" in msgs[0]


def test_repeat_calls_stay_silent():
    reg = {"never_ready_win4": _NeverReady(), "always_ok_win4": _AlwaysOk()}
    msgs = []
    prune_unavailable(reg, emit=msgs.append)          # 1ª vez: avisa
    prune_unavailable(reg, emit=msgs.append)          # 2ª, 3ª... vez: silêncio (já avisou)
    prune_unavailable(reg, emit=msgs.append)
    assert len(msgs) == 1


def test_reset_allows_warning_again():
    reg = {"never_ready_win4": _NeverReady()}
    msgs = []
    prune_unavailable(reg, emit=msgs.append)
    reset_unavailable_warnings()
    prune_unavailable(reg, emit=msgs.append)
    assert len(msgs) == 2


def test_multiple_unavailable_tools_batch_into_one_line():
    class _A(Tool):
        name = "batch_a_win4"
        description = "x"
        args_schema = {}

        def check(self):
            return "falta lib a"

    class _B(Tool):
        name = "batch_b_win4"
        description = "x"
        args_schema = {}

        def check(self):
            return "falta lib b"

    msgs = []
    prune_unavailable({"batch_a_win4": _A(), "batch_b_win4": _B()}, emit=msgs.append)
    assert len(msgs) == 1
    assert "batch_a_win4" in msgs[0] and "batch_b_win4" in msgs[0]
