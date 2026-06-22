"""Compat de plataforma — o agente roda em Windows, macOS e Linux (VPS headless ou desktop). Centraliza o
que difere entre POSIX e Windows pra não espalhar branches frágeis: kwargs de Popen p/ desacoplar um
processo de background, encerrar um processo (e o grupo, no POSIX), e restringir a permissão de um arquivo
de SEGREDO/CHAVE. No POSIX usa chmod 0600 e VERIFICA; no Windows usa ACL (icacls owner-only).
"""
from __future__ import annotations

import os
import subprocess  # nosec B404 — usa argv FIXO (taskkill/icacls), sem shell
from pathlib import Path

IS_WINDOWS = os.name == "nt"
IS_POSIX = os.name == "posix"


def popen_session_kwargs() -> dict:
    """kwargs p/ subprocess.Popen desacoplar o filho do grupo/sessão do pai (process_start em background).
    POSIX: start_new_session=True. Windows: creationflags (DETACHED_PROCESS + novo grupo) — lá
    start_new_session levanta ValueError."""
    if IS_WINDOWS:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": flags}
    return {"start_new_session": True}


def terminate_pid(pid: int, sig=None) -> bool:
    """Encerra um processo de forma cross-plataforma. POSIX: mata o GRUPO (killpg → pega filhos de
    start_new_session), com fallback no pid. Windows: os.kill e, em último caso, taskkill /T (árvore).
    Devolve True se algo foi sinalizado. getpgid/killpg NÃO existem no Windows → guardado por hasattr."""
    import signal as _signal
    sig = sig if sig is not None else getattr(_signal, "SIGTERM", 15)
    if IS_POSIX and hasattr(os, "killpg") and hasattr(os, "getpgid"):
        try:
            os.killpg(os.getpgid(pid), sig)
            return True
        except (AttributeError, OSError, ProcessLookupError):
            pass
    try:
        os.kill(pid, sig)
        return True
    except (AttributeError, OSError, ProcessLookupError):
        pass
    if IS_WINDOWS:                                      # último recurso: encerra a árvore pela CLI do Windows
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],  # nosec B603,B607
                           capture_output=True, timeout=10, check=False)
            return True
        except (OSError, subprocess.SubprocessError):
            pass
    return False


def secure_chmod(path, *, mode: int = 0o600) -> bool:
    """Restringe um arquivo de SEGREDO/CHAVE ao dono. POSIX: chmod + VERIFICA (False se o FS não aplicou —
    o caller recusa segredo frouxo). Windows: NTFS ACL via icacls (remove herança, dá controle só ao
    usuário) — chmod lá é no-op e o ssh recusa chave com permissão larga. Devolve True se restringiu."""
    p = Path(path)
    if IS_POSIX:
        try:
            os.chmod(p, mode)
            return (p.stat().st_mode & 0o777) == mode
        except OSError:
            return False
    if IS_WINDOWS:
        user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        if not user:
            return False
        try:
            r = subprocess.run(["icacls", str(p), "/inheritance:r", "/grant:r", f"{user}:F"],  # nosec B603,B607
                               capture_output=True, timeout=15, check=False)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    return False


__all__ = ["IS_WINDOWS", "IS_POSIX", "popen_session_kwargs", "terminate_pid", "secure_chmod"]
