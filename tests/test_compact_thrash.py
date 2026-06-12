"""Anti-thrashing de compactação (pesquisa #5 item 2, paridade Hermes).

Quando 2 compactações PESADAS seguidas rendem <10% de ganho cada, o contexto está saturado de
conteúdo incompressível (tail gigante) — continuar compactando a cada turno é thrash puro. O
harness PARA com falha honesta sugerindo /new (e tenta a entrega parcial via salvage normal).
"""
from __future__ import annotations

import okami.core.harness.loop as loop_mod
from okami.core import Task
from okami.core.harness import Harness
from okami.core.harness.models import Budget


def _h(tmp_path, gen=None):
    return Harness(generate=gen or (lambda m, s: ""), task=Task(goal="oi"), workspace=tmp_path)


def test_low_gain_counter_trips_on_second_consecutive(tmp_path):
    h = _h(tmp_path)
    assert h._note_compact_gain(1000, 950) is False     # 5% — 1ª vez, ainda não
    assert h._note_compact_gain(1000, 990) is True      # 2ª seguida <10% → thrash


def test_effective_compaction_resets_counter(tmp_path):
    h = _h(tmp_path)
    assert h._note_compact_gain(1000, 950) is False     # 5%
    assert h._note_compact_gain(1000, 500) is False     # 50% — funcionou → reseta
    assert h._note_compact_gain(1000, 950) is False     # 5% — conta como 1ª de novo
    assert h._note_compact_gain(1000, 920) is True      # 2ª seguida


def test_thrashing_stops_run_and_suggests_new(tmp_path, monkeypatch):
    # contexto SEMPRE acima do teto e compact não reduz nada → 2 turnos depois, para sugerindo /new
    def gen(messages, schema):
        return '{"tool": "list_dir", "args": {"path": "."}}'

    monkeypatch.setattr(loop_mod._compaction, "estimate_chars", lambda m: 30000)
    monkeypatch.setattr(loop_mod._compaction, "prune_observations", lambda m, **k: (m, 0))
    monkeypatch.setattr(loop_mod._compaction, "compact", lambda m, mem, **k: (m, 0))
    h = Harness(generate=gen, task=Task(goal="oi"), workspace=tmp_path,
                budget=Budget(max_context_chars=24000))
    res = h.run()
    assert res.state.name == "FAILED"
    assert "/new" in (res.reason or "")
