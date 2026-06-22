"""Tools de operação da VPS: system_monitor (saúde do host) + restart_gateway (auto-reinício). O agente
precisa disso pra se virar sozinho — checar recurso antes de tarefa pesada e recuperar o próprio gateway."""
from __future__ import annotations


def test_host_stats_always_has_disk(tmp_path):
    """Disco vem via shutil.disk_usage (stdlib) → SEMPRE presente nas 3 plataformas, mesmo sem psutil."""
    from okami.core import sysmon
    st = sysmon.host_stats(str(tmp_path))
    assert "disk" in st and st["disk"]["total_gb"] > 0 and "free_gb" in st["disk"]


def test_health_flags_low_disk():
    from okami.core import sysmon
    flags = sysmon.health_flags({"disk": {"free_gb": 0.3, "total_gb": 50, "used_pct": 99.4}})
    assert any("disco" in f for f in flags)               # alerta acionável de disco cheio


def test_system_monitor_tool_reports_disk(tmp_path):
    from okami.core.tools.base import ToolContext
    from okami.core.tools.sysops import SystemMonitor
    res = SystemMonitor().run({}, ToolContext(workspace=tmp_path))
    assert res.ok and "disco" in res.output.lower()       # legível p/ o modelo
    assert res.content and "disk" in res.content          # dado estruturado p/ decisão


def test_restart_gateway_tool_delegates(monkeypatch):
    from okami.core.tools.base import ToolContext
    from okami.core.tools import sysops
    called = []
    monkeypatch.setattr("okami.gateway.restart.schedule_self_restart",
                        lambda: (called.append(True) or (True, "reiniciando…")))
    res = sysops.RestartGateway().run({}, ToolContext(workspace="."))
    assert res.ok and called == [True] and "reinici" in res.output.lower()


def test_sysops_tools_registered():
    from okami.core.tool_registry import TOOL_REGISTRY
    from okami.core.tools.registry import default_registry
    reg = default_registry()
    assert "system_monitor" in reg and "restart_gateway" in reg
    specs = {s.name: s for s in TOOL_REGISTRY}
    assert specs["restart_gateway"].danger == "sensitive"  # disruptivo → approval-gated
    assert specs["system_monitor"].danger == "safe"        # read-only


def test_computer_use_pruned_on_headless_linux(monkeypatch):
    """Confirma o fix da rodada passada: sem $DISPLAY no Linux → get_backend()=None → computer_use é PODADA
    (não promete controle de tela numa VPS headless)."""
    import sys
    import okami.core.computeruse.backend as bk
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    assert bk.get_backend() is None
