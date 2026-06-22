"""Compat de plataforma — o agente roda em Windows, macOS e Linux. Centraliza o que difere entre POSIX e
Windows (kwargs de Popen p/ desacoplar processo, encerrar processo/grupo, restringir permissão de segredo)."""
from __future__ import annotations

import okami.core.platform_compat as pc


def test_popen_session_kwargs_posix(monkeypatch):
    monkeypatch.setattr(pc, "IS_WINDOWS", False)
    assert pc.popen_session_kwargs() == {"start_new_session": True}


def test_popen_session_kwargs_windows(monkeypatch):
    monkeypatch.setattr(pc, "IS_WINDOWS", True)
    kw = pc.popen_session_kwargs()
    assert "creationflags" in kw and "start_new_session" not in kw   # Windows não aceita start_new_session


def test_secure_chmod_posix_sets_600(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "IS_WINDOWS", False)
    monkeypatch.setattr(pc, "IS_POSIX", True)
    f = tmp_path / "key"
    f.write_text("x", encoding="utf-8")
    assert pc.secure_chmod(f) is True
    assert oct(f.stat().st_mode)[-3:] == "600"                       # restringiu ao dono


def test_secure_chmod_posix_returns_false_if_chmod_noop(tmp_path, monkeypatch):
    """No POSIX, se o chmod NÃO pegou (FS sem suporte), retorna False — o caller decide recusar segredo frouxo."""
    monkeypatch.setattr(pc, "IS_WINDOWS", False)
    monkeypatch.setattr(pc, "IS_POSIX", True)
    monkeypatch.setattr(pc.os, "chmod", lambda *a, **k: None)        # finge chmod que não altera o modo
    f = tmp_path / "key"
    f.write_text("x", encoding="utf-8")
    import os as _os
    _os.chmod(f, 0o644)                                              # modo frouxo de verdade
    assert pc.secure_chmod(f) is False


def test_terminate_pid_falls_back_to_os_kill(monkeypatch):
    monkeypatch.setattr(pc, "IS_POSIX", False)                       # pula o caminho killpg
    monkeypatch.setattr(pc, "IS_WINDOWS", False)
    killed = []
    monkeypatch.setattr(pc.os, "kill", lambda pid, sig: killed.append(pid))
    assert pc.terminate_pid(4321) is True and killed == [4321]


def test_terminate_pid_posix_uses_group(monkeypatch):
    monkeypatch.setattr(pc, "IS_POSIX", True)
    monkeypatch.setattr(pc, "IS_WINDOWS", False)
    grp = []
    monkeypatch.setattr(pc.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(pc.os, "killpg", lambda pgid, sig: grp.append(pgid))
    assert pc.terminate_pid(99) is True and grp == [99]              # mata o GRUPO (pega filhos)
