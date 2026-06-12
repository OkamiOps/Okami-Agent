"""/insights — analytics histórico cross-sessão (pesquisa #6 item 21, paridade Hermes insights).

Agrega o event log (llm_call: provider/model/surface/tokens/ts) por período: total + breakdown por
dia, modelo, provider e PLATAFORMA. "Quanto gastei essa semana e em qual canal." Os dados já são
coletados pelo harness; isto é o agregador que faltava.
"""
from __future__ import annotations

import json
from pathlib import Path

from okami.observability import insights


def _write_events(ws: Path, rows: list[dict]):
    d = ws / ".okami"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "events.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"type": "llm_call", **r}) + "\n")


_DAY = 86400.0


def test_aggregates_totals_and_breakdowns(tmp_path):
    now = 1_000_000.0
    _write_events(tmp_path, [
        {"ts": now - 1 * _DAY, "provider": "codex", "model": "gpt-5", "surface": "telegram",
         "tokens_in": 100, "tokens_out": 20, "cache": 50},
        {"ts": now - 1 * _DAY, "provider": "codex", "model": "gpt-5", "surface": "cli",
         "tokens_in": 200, "tokens_out": 40, "cache": 0},
        {"ts": now - 2 * _DAY, "provider": "claude", "model": "opus", "surface": "telegram",
         "tokens_in": 300, "tokens_out": 60, "cache": 10},
    ])
    rep = insights.collect(tmp_path, days=30, now=lambda: now)
    assert rep["calls"] == 3
    assert rep["tokens_in"] == 600 and rep["tokens_out"] == 120 and rep["cache"] == 60
    assert rep["by_model"]["gpt-5"]["tokens_in"] == 300 and rep["by_model"]["gpt-5"]["calls"] == 2
    assert rep["by_provider"]["claude"]["tokens_in"] == 300
    assert rep["by_surface"]["telegram"]["calls"] == 2
    assert rep["by_surface"]["cli"]["tokens_in"] == 200
    assert len(rep["by_day"]) == 2                     # 2 dias distintos


def test_window_filters_old_events(tmp_path):
    now = 1_000_000.0
    _write_events(tmp_path, [
        {"ts": now - 2 * _DAY, "provider": "codex", "model": "m", "surface": "cli",
         "tokens_in": 10, "tokens_out": 1},
        {"ts": now - 40 * _DAY, "provider": "codex", "model": "m", "surface": "cli",
         "tokens_in": 999, "tokens_out": 99},   # fora da janela de 7 dias
    ])
    rep = insights.collect(tmp_path, days=7, now=lambda: now)
    assert rep["calls"] == 1 and rep["tokens_in"] == 10


def test_empty_when_no_events(tmp_path):
    rep = insights.collect(tmp_path, days=30, now=lambda: 1_000_000.0)
    assert rep["calls"] == 0 and rep["tokens_in"] == 0
    assert rep["by_model"] == {} and rep["by_surface"] == {}


def test_render_human_text(tmp_path):
    now = 1_000_000.0
    _write_events(tmp_path, [
        {"ts": now - _DAY, "provider": "codex", "model": "gpt-5", "surface": "telegram",
         "tokens_in": 1000, "tokens_out": 200}])
    rep = insights.collect(tmp_path, days=7, now=lambda: now)
    text = insights.render(rep)
    assert "gpt-5" in text and "telegram" in text
    assert "7" in text                                # menciona a janela de dias
    assert "1" in text                                # menciona contagem/tokens


def test_ignores_non_llm_events(tmp_path):
    d = tmp_path / ".okami"
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text(
        json.dumps({"type": "step", "ts": 1_000_000.0, "tool": "read_file"}) + "\n"
        + json.dumps({"type": "llm_call", "ts": 1_000_000.0, "provider": "codex", "model": "m",
                      "tokens_in": 5, "tokens_out": 1}) + "\n", encoding="utf-8")
    rep = insights.collect(tmp_path, days=30, now=lambda: 1_000_001.0)
    assert rep["calls"] == 1 and rep["tokens_in"] == 5
