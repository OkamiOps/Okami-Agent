"""Watchdog de memória (paridade Hermes gateway/memory_monitor): thread daemon que loga RSS + nº de
threads + uptime a cada N segundos, num formato GREPÁVEL `[MEMORY] rss=…MB threads=… uptime=…s`. Sem
dependência extra — usa `resource.getrusage` (Linux/macOS). Detecção de vazamento lento = grep `[MEMORY]`
e ver o RSS subir ao longo das horas. Nunca derruba o processo (best-effort, exceções engolidas)."""

from __future__ import annotations

import gc
import threading
import time


def _rss_mb() -> int:
    """RSS em MB via resource (stdlib). ru_maxrss é KB no Linux, BYTES no macOS — normaliza."""
    try:
        import resource
        import sys
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(maxrss / 1024 / 1024) if sys.platform == "darwin" else int(maxrss / 1024)
    except Exception:  # noqa: BLE001 — sem resource (Windows) → 0 (degrada quieto)
        return 0


def memory_sample(start: float, now: float | None = None) -> dict:
    now = time.monotonic() if now is None else now
    return {"rss_mb": _rss_mb(), "threads": threading.active_count(),
            "uptime_s": int(now - start), "gc": gc.get_count()}


def format_memory_line(s: dict) -> str:
    return (f"[MEMORY] rss={s['rss_mb']}MB threads={s['threads']} "
            f"uptime={s['uptime_s']}s gc={s.get('gc', ())}")


def _tick(emit, start: float, now: float | None = None) -> None:
    try:
        emit(format_memory_line(memory_sample(start, now)))
    except Exception:  # noqa: BLE001 — watchdog nunca derruba o gateway
        pass


def start_memory_watch(emit, interval: float = 300.0) -> threading.Thread:
    """Sobe a thread daemon. Loga uma baseline na hora e depois a cada `interval`s."""
    start = time.monotonic()

    def loop():
        _tick(emit, start)                  # baseline imediata
        while True:
            time.sleep(interval)
            _tick(emit, start)

    th = threading.Thread(target=loop, daemon=True)
    th.start()
    return th
