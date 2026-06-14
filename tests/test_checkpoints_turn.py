"""Item 17 — undo agrupado por TURNO: snapshots carimbados com trace, rollback_turn, turns().

Estende os checkpoints (#3/#5/#10) para que cada escrita carregue o `trace` do turno corrente
(setado por `begin_turn`). `rollback_turn(trace)` desfaz TODAS as escritas daquele turno em ordem
reversa; `turns()` lista os turnos com contagem. O campo `trace` é OPCIONAL (default None) → entradas
antigas (sem trace) seguem com a cadeia HMAC íntegra e os testes legados (#3/#5/#10) verdes.
"""

from __future__ import annotations

import json

from okami.gateway.checkpoints import Checkpoints


def test_begin_turn_stamps_trace_on_snapshot(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    cp = Checkpoints(ws)
    cp.begin_turn("t-abc")
    cp.snapshot("a.txt")
    ents = cp.entries()
    assert len(ents) == 1
    assert ents[0].get("trace") == "t-abc"                 # carimbado pelo turno corrente


def test_snapshot_without_begin_turn_has_none_trace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("v1", encoding="utf-8")
    cp = Checkpoints(ws)
    cp.snapshot("a.txt")                                   # sem begin_turn → trace ausente/None
    ents = cp.entries()
    assert ents[0].get("trace") is None
    assert all(cp._verify(ents))                           # cadeia HMAC íntegra mesmo sem trace


def test_hmac_chain_intact_with_trace_field(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    f = ws / "a.txt"
    cp = Checkpoints(ws)
    cp.begin_turn("t-1")
    f.write_text("1", encoding="utf-8")
    cp.snapshot("a.txt")
    f.write_text("2", encoding="utf-8")
    cp.snapshot("a.txt")
    cp.begin_turn("t-2")
    f.write_text("3", encoding="utf-8")
    cp.snapshot("a.txt")
    assert all(cp._verify(cp.entries()))                   # 3 entradas, 2 turnos → cadeia bate


def test_rollback_turn_reverts_only_that_turn(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    a = ws / "a.txt"
    b = ws / "b.txt"
    cp = Checkpoints(ws)
    # turno 1: cria a.txt (não existia) + b.txt (não existia)
    cp.begin_turn("t-1")
    a.write_text("a-v1", encoding="utf-8")
    cp.snapshot("a.txt")                                   # antes: não existia
    a.write_text("a-final-t1", encoding="utf-8")
    cp.snapshot("b.txt")                                   # antes: não existia
    b.write_text("b-final-t1", encoding="utf-8")
    # turno 2: sobrescreve a.txt
    cp.begin_turn("t-2")
    cp.snapshot("a.txt")                                   # antes: "a-final-t1"
    a.write_text("a-v2", encoding="utf-8")

    reverted = cp.rollback_turn("t-2")
    assert reverted == ["a.txt"]                           # só a escrita do turno 2
    assert a.read_text(encoding="utf-8") == "a-final-t1"   # voltou ao estado de antes do t-2
    assert b.read_text(encoding="utf-8") == "b-final-t1"   # b NÃO foi tocado (era do t-1)


def test_rollback_turn_reverse_order_and_deletes(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    a = ws / "a.txt"
    cp = Checkpoints(ws)
    cp.begin_turn("t-1")
    cp.snapshot("a.txt")                                   # não existia
    a.write_text("primeiro", encoding="utf-8")
    cp.snapshot("a.txt")                                   # existia ("primeiro")
    a.write_text("segundo", encoding="utf-8")
    # reverter o turno em ordem reversa: desfaz "segundo"→"primeiro", depois "primeiro"→inexistente
    cp.rollback_turn("t-1")
    assert not a.exists()                                  # ao final do turno, o arquivo não existia


def test_rollback_turn_drops_reverted_entries_from_journal(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    a = ws / "a.txt"
    cp = Checkpoints(ws)
    cp.begin_turn("t-1")
    a.write_text("1", encoding="utf-8")
    cp.snapshot("a.txt")
    cp.begin_turn("t-2")
    a.write_text("2", encoding="utf-8")
    cp.snapshot("a.txt")
    cp.rollback_turn("t-1")
    remaining = cp.entries()
    assert all(e.get("trace") != "t-1" for e in remaining)  # entradas do t-1 saíram do journal
    assert any(e.get("trace") == "t-2" for e in remaining)  # o t-2 continua
    assert all(cp._verify(remaining))                       # e re-encadeou íntegro


def test_turns_lists_traces_with_count(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    a = ws / "a.txt"
    cp = Checkpoints(ws)
    cp.begin_turn("t-1")
    a.write_text("1", encoding="utf-8")
    cp.snapshot("a.txt")
    a.write_text("2", encoding="utf-8")
    cp.snapshot("a.txt")
    cp.begin_turn("t-2")
    a.write_text("3", encoding="utf-8")
    cp.snapshot("a.txt")
    turns = cp.turns()
    by_trace = {tr: cnt for tr, cnt, ts in turns}
    assert by_trace["t-1"] == 2
    assert by_trace["t-2"] == 1


def test_turns_ignores_tampered_entries(tmp_path):
    """Entrada com HMAC quebrado não conta como turno legítimo (igual ao rollback)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    a = ws / "a.txt"
    cp = Checkpoints(ws)
    cp.begin_turn("t-1")
    a.write_text("1", encoding="utf-8")
    cp.snapshot("a.txt")
    # injeta uma entrada forjada com trace fantasma e mac inválido
    ents = cp.entries()
    forged = {"path": "a.txt", "before": "x", "existed": True, "ts": 1.0,
              "trace": "t-evil", "mac": "deadbeef"}
    cp.journal.write_text(
        "\n".join(json.dumps(e) for e in ents + [forged]) + "\n", encoding="utf-8")
    turns = cp.turns()
    traces = {tr for tr, _c, _ts in turns}
    assert "t-1" in traces
    assert "t-evil" not in traces                          # forjada ignorada


def test_rollback_turn_skips_tampered_entries(tmp_path):
    """rollback_turn reusa a verificação HMAC: entrada forjada do trace alvo é ignorada."""
    ws = tmp_path / "ws"
    ws.mkdir()
    a = ws / "a.txt"
    a.write_text("legit", encoding="utf-8")
    cp = Checkpoints(ws)
    cp.begin_turn("t-1")
    cp.snapshot("a.txt")
    a.write_text("v2", encoding="utf-8")
    # atacante troca o `before` da entrada do t-1 → quebra o mac
    ents = cp.entries()
    ents[0]["before"] = "PWNED"
    cp.journal.write_text(json.dumps(ents[0]) + "\n", encoding="utf-8")
    reverted = cp.rollback_turn("t-1")
    assert reverted == [] and a.read_text(encoding="utf-8") == "v2"   # mac não bate → não restaura
