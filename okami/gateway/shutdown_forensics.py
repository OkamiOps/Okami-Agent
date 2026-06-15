"""Forense de shutdown — contexto best-effort de QUEM/COMO nos matou (gateway/shutdown_forensics.py).

Quando o gateway recebe SIGTERM/SIGINT (ou cai), saber QUEM mandou o sinal e SOB QUE supervisor
estávamos rodando vira ouro pra depurar restarts misteriosos: foi o systemd reciclando o serviço?
o `okami gateway restart` se matando? OOM-killer? Este módulo tira um retrato barato do ambiente
no instante da morte — pid/ppid, comando do pai, sinal, se há supervisor, carga da máquina.

Cross-platform (macOS+Linux via stdlib), e ACIMA DE TUDO fail-safe: estamos morrendo, então nada
aqui pode levantar e atrapalhar o shutdown gracioso — cada campo degrada pra "" / None isolado.
"""
from __future__ import annotations

import os
import signal as _signal
import subprocess

from okami.core.redact import redact


def _signal_name(signum: int | None) -> str:
    """Nome legível do sinal (ex.: 'SIGTERM') ou "" se não informado/desconhecido."""
    if signum is None:
        return ""
    try:
        return _signal.Signals(signum).name          # 15 → 'SIGTERM'
    except (ValueError, KeyError, OverflowError):
        return str(signum)                            # número desconhecido: ainda é informação útil


def _parent_cmd(ppid: int) -> str:
    """Linha de comando do processo pai via `ps` (best-effort, timeout curto; "" se falhar).

    Usa `ps -o command= -p <ppid>` — portável em macOS e Linux. Redige por garantia: linha de
    comando de pai pode carregar `--token=…` e isto pode virar log.
    """
    if ppid <= 0:
        return ""
    try:
        out = subprocess.run(
            ["ps", "-o", "command=", "-p", str(ppid)],
            capture_output=True, text=True, timeout=2.0, check=False,
        )
        return redact(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""                                     # sem `ps`, sem permissão, timeout: segue a vida


def _under_systemd(ppid: int) -> bool:
    """True se parece estar sob supervisor: env INVOCATION_ID (systemd) OU reparenteado pro init."""
    try:
        if os.environ.get("INVOCATION_ID"):           # systemd injeta isto em unidades de serviço
            return True
        return ppid == 1                              # pai == init: rodando como serviço/órfão adotado
    except Exception:
        return False


def _loadavg() -> tuple[float, float, float] | None:
    """Carga média (1/5/15 min) como tupla, ou None onde não existe (Windows)."""
    try:
        return tuple(os.getloadavg())                 # type: ignore[return-value]
    except (OSError, AttributeError):
        return None


def snapshot_shutdown_context(signum: int | None = None) -> dict:
    """Retrato barato do ambiente no instante do shutdown. Best-effort: nunca levanta.

    Campos: signal (nome do sinal ou ""), pid, ppid, parent_cmd (comando do pai ou ""),
    under_systemd (bool), loadavg (tupla 1/5/15 ou None no Windows).
    """
    try:
        pid = os.getpid()
    except Exception:
        pid = -1
    try:
        ppid = os.getppid()
    except Exception:
        ppid = -1
    return {
        "signal": _signal_name(signum),
        "pid": pid,
        "ppid": ppid,
        "parent_cmd": _parent_cmd(ppid),
        "under_systemd": _under_systemd(ppid),
        "loadavg": _loadavg(),
    }


def format_context(ctx: dict) -> str:
    """Achata o snapshot numa linha legível p/ log. Fail-safe: dict capenga → ainda devolve string."""
    try:
        sig = ctx.get("signal") or "?"
        pid = ctx.get("pid", "?")
        ppid = ctx.get("ppid", "?")
        parts = [f"shutdown signal={sig} pid={pid} ppid={ppid}"]
        parent = ctx.get("parent_cmd")
        if parent:
            parts.append(f"parent='{parent}'")
        if ctx.get("under_systemd"):
            parts.append("under_systemd=yes")
        load = ctx.get("loadavg")
        if load:
            parts.append("load=" + "/".join(f"{x:.2f}" for x in load))
        return " ".join(parts)
    except Exception:
        return "shutdown context unavailable"         # melhor uma linha pobre que estourar no death-path
