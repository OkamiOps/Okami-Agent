"""Auditoria de portabilidade (Win/Mac/Linux × VPS/local) — fixes verificáveis sem o SO-alvo presente."""
from __future__ import annotations


def test_pyautogui_backend_unavailable_on_headless_linux(monkeypatch):
    """Linux SEM $DISPLAY (VPS headless): pyautogui importa mas screenshot/click crasham → available()=False
    (a tool é PODADA em vez de quebrar em runtime)."""
    import sys
    import okami.core.computeruse.backend as bk
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    assert bk.PyAutoGuiBackend().available() is False  # headless Linux → poda (não crasha em runtime)


def test_render_systemd_target_by_scope():
    """Serviço de SISTEMA (root) → multi-user.target (boota sem login na VPS); user-service → default.target."""
    from okami.gateway.service import render_systemd
    argv, wd, log, home = ["okami", "gateway"], "/wd", "/var/log/okami.log", "/home/okami"
    assert "WantedBy=default.target" in render_systemd(argv, wd, log, home, system=False)
    assert "WantedBy=multi-user.target" in render_systemd(argv, wd, log, home, system=True)


def test_browser_fetch_uses_headless(monkeypatch):
    """As duas chamadas de launch_persistent_context passam headless=True (senão crasha em VPS sem display)."""
    import inspect
    import okami.integrations.browser as br
    src = inspect.getsource(br)
    assert "launch_persistent_context(user_data_dir=str(profile))" not in src     # nenhuma chamada SEM headless
    assert src.count("launch_persistent_context(") >= 2                            # as duas existem
