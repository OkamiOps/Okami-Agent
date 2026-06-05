"""Lock cross-platform por arquivo (.lock atômico O_EXCL) — concorrência multi-processo (P0.5).

Promovido de gateway/sessions.py p/ o núcleo: sessões, checkpoints e qualquer escrita
read-modify-write entre processos usam o MESMO lock. O lock guarda o DONO (pid + start-time):
rouba só se o dono MORREU (os.kill(pid,0) / start-time mudou = PID reciclado) ou se está velho
demais. Ao soltar, remove só o lock que EU criei. atexit solta os meus; crash é coberto pelo
stale-reclaim. Sem dependência externa (fcntl não é portável p/ macOS+Win uniformemente).
"""

from __future__ import annotations

import atexit
import json
import os
import time
from pathlib import Path

_HELD: set[str] = set()        # locks deste processo (p/ limpar na saída)


def _proc_start(pid: int) -> str:
    """Start-time do processo (Linux /proc, campo 22) p/ detectar PID RECICLADO. '' onde não dá (macOS/Win)."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            raw = f.read()
        return raw[raw.rfind(")") + 1:].split()[19]      # após o comm: starttime é o 20º token (campo 22)
    except Exception:  # noqa: BLE001
        return ""


def _cleanup_held_locks() -> None:
    """Solta os locks DESTE processo na saída (atexit). Crash/SIGTERM é coberto pelo stale-reclaim."""
    for lk in list(_HELD):
        try:
            if int(json.loads(Path(lk).read_text(encoding="utf-8")).get("pid", -1)) == os.getpid():
                Path(lk).unlink()
        except Exception:  # noqa: BLE001
            pass


atexit.register(_cleanup_held_locks)


class _FileLock:
    """Lock por arquivo. Rouba só se o dono morreu ou ficou velho; remove só o que eu criei."""

    def __init__(self, target: Path, timeout: float = 10.0, stale: float = 60.0):
        self.lock = Path(str(target) + ".lock")
        self.timeout, self.stale = timeout, stale
        self.acquired = False

    def _owner_alive(self) -> bool:
        try:
            info = json.loads(self.lock.read_text(encoding="utf-8"))
            pid = int(info.get("pid", 0))
        except Exception:  # noqa: BLE001 — lock recém-criado/meio-escrito (janela entre create e write):
            return True     # assume VIVO p/ NÃO roubar (evita corrida); `age > stale` ainda reclama o real-órfão
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)                               # processo vivo? (POSIX; ProcessLookupError se morto)
        except ProcessLookupError:
            return False
        except OSError:
            return True                                  # sem permissão p/ sinalizar → existe (conservador)
        stored, cur = info.get("start", ""), _proc_start(pid)   # anti PID-reuse: start-time diferente = outro proc
        return not (stored and cur and stored != cur)

    def _age(self) -> float:
        try:
            return time.time() - self.lock.stat().st_mtime
        except OSError:
            return 0.0

    def __enter__(self):
        start = time.time()
        while True:
            try:
                fd = os.open(str(self.lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, json.dumps({"pid": os.getpid(), "start": _proc_start(os.getpid()),
                                         "created": time.time()}).encode("utf-8"))
                os.close(fd)
                self.acquired = True
                _HELD.add(str(self.lock))                # registra p/ limpeza na saída (atexit)
                return self
            except FileExistsError:
                if not self._owner_alive() or self._age() > self.stale:   # dono morto OU velho → rouba
                    try:
                        self.lock.unlink()
                    except OSError:
                        pass
                    continue
                if time.time() - start > self.timeout:
                    from okami.log import warn
                    warn(f"lock ocupado >{self.timeout:.0f}s ({self.lock.name}) — seguindo sem lock")
                    return self                          # best-effort, mas agora REGISTRA
                time.sleep(0.03)

    def __exit__(self, *exc):
        if self.acquired:                                # só removo o lock que EU criei
            _HELD.discard(str(self.lock))
            try:
                self.lock.unlink()
            except OSError:
                pass
