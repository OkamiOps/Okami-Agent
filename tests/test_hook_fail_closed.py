"""Hook de BLOQUEIO (before_*) que EXPLODE deve falhar FECHADO (vetar), não aberto (paridade Hermes:
o caminho de bloqueio é estruturado, não 'exceção→permite'). Um hook de política de segurança que erra
não pode liberar exatamente a ação que existe pra barrar."""
from __future__ import annotations

import okami.automation.hooks as H
from okami.automation.hooks import HookManager


def test_blocking_hook_error_fails_closed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("hook explodiu")
    monkeypatch.setattr(H.subprocess, "run", boom)
    hm = HookManager(root=".")
    assert hm._run_cmd("x", "before_tool", {}) is False    # BLOCKABLE → erro VETA (fail-closed)
    assert hm._run_cmd("x", "before_write", {}) is False
    assert hm._run_cmd("x", "after_tool", {}) is True       # observer → erro não veta (sem efeito)
