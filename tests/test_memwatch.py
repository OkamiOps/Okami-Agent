"""Watchdog de memória (paridade Hermes memory_monitor): thread daemon loga RSS+threads+uptime num
formato grepável `[MEMORY]` p/ flagrar vazamento lento em produção. Sem dep extra (usa resource)."""

from __future__ import annotations

from okami.observability.memwatch import format_memory_line, memory_sample, _tick


def test_sample_has_fields():
    s = memory_sample(start=0.0, now=3600.0)
    assert s["rss_mb"] >= 0 and s["threads"] >= 1 and s["uptime_s"] == 3600


def test_format_is_grep_friendly():
    line = format_memory_line({"rss_mb": 150, "threads": 12, "uptime_s": 3600, "gc": (100, 20, 5)})
    assert line.startswith("[MEMORY]")
    assert "rss=150MB" in line and "threads=12" in line and "uptime=3600s" in line


def test_tick_emits_one_line():
    out: list[str] = []
    _tick(out.append, start=0.0, now=10.0)
    assert len(out) == 1 and out[0].startswith("[MEMORY]")


def test_tick_survives_emit_error():
    def boom(_):
        raise RuntimeError("emit quebrou")
    _tick(boom, start=0.0, now=10.0)                       # não levanta — watchdog nunca derruba o gateway
