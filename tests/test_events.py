"""Event log estruturado (JSONL): emite, lê, mascara segredo e o harness alimenta o timeline."""

from __future__ import annotations

from okami.observability.events import EventLog, read_events


def test_emit_and_read_roundtrip(tmp_path):
    log = EventLog(tmp_path)
    log.emit("start", goal="fazer X")
    log.emit("step", n=1, tool="write_file", ok=True)
    log.emit("complete", summary="feito")
    evs = read_events(tmp_path)
    assert [e["type"] for e in evs] == ["start", "step", "complete"]
    assert [e["seq"] for e in evs] == [1, 2, 3]          # seq monotônico
    assert evs[1]["tool"] == "write_file" and evs[1]["ok"] is True
    assert all("ts" in e for e in evs)


def test_events_are_redacted(tmp_path):
    EventLog(tmp_path).emit("step", out="OPENAI_API_KEY=sk-abcdefghijklmnop1234")  # pragma: allowlist secret
    line = (tmp_path / ".okami" / "events.jsonl").read_text(encoding="utf-8")
    assert "sk-abcdefghijklmnop1234" not in line and "redacted" in line  # pragma: allowlist secret


def test_read_missing_is_empty(tmp_path):
    assert read_events(tmp_path) == []


def test_harness_emit_writes_timeline(tmp_path):
    """O harness persiste o timeline via _emit (sem rodar um provider de verdade)."""
    from okami.core.harness import Harness
    h = Harness.__new__(Harness)                          # evita o __init__ completo no teste
    h.events = EventLog(tmp_path)
    h.on_event = lambda e: None
    h._emit("start", goal="oi")
    h._emit("step", n=1, tool="run_shell", ok=False)
    evs = read_events(tmp_path)
    assert [e["type"] for e in evs] == ["start", "step"]
    assert evs[1]["ok"] is False
