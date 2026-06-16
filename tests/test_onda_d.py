"""#12 Onda D: ecossistema de plugins + browser supervisor (CDP) + web dashboard/gui."""
from __future__ import annotations


# ── plugins: descoberta (pasta + entry-point) ──
def test_discover_plugins_from_folder(tmp_path):
    from okami.plugins import discover_plugins
    pdir = tmp_path / "plugins" / "meu-plugin"
    pdir.mkdir(parents=True)
    (pdir / "plugin.yaml").write_text("name: meu-plugin\nhooks: [pre_llm_call]\n", encoding="utf-8")
    plugins = discover_plugins([tmp_path], entry_points=())
    assert any(p.name == "meu-plugin" and "pre_llm_call" in p.hooks for p in plugins)


def test_discover_plugins_from_entry_points():
    from okami.plugins import discover_plugins
    from types import SimpleNamespace
    ep = SimpleNamespace(name="ep-plugin", value="mod:obj")
    plugins = discover_plugins([], entry_points=(ep,))
    assert any(p.name == "ep-plugin" and p.source == "entry_point" for p in plugins)


def test_discover_ignores_bad_plugin(tmp_path):
    from okami.plugins import discover_plugins
    bad = tmp_path / "plugins" / "quebrado"
    bad.mkdir(parents=True)
    (bad / "plugin.yaml").write_text("name: [unclosed\n", encoding="utf-8")  # YAML quebrado
    assert discover_plugins([tmp_path], entry_points=()) == []               # ignora, não crasha


def test_plugin_hooks_execute_and_can_veto(tmp_path):
    from okami.automation.hooks import HookManager
    # plugin com um hook before_tool que VETA (exit 1)
    hookdir = tmp_path / "plugins" / "guard" / "hooks" / "before_tool"
    hookdir.mkdir(parents=True)
    (tmp_path / "plugins" / "guard" / "plugin.yaml").write_text("name: guard\nhooks: [before_tool]\n", encoding="utf-8")
    veto = hookdir / "veto.sh"
    veto.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    veto.chmod(0o755)
    hm = HookManager(root=str(tmp_path))
    assert hm.fire("before_tool", {"tool": "run_shell"}) is False    # hook de PLUGIN vetou
    assert hm.events().get("before_tool", 0) >= 1                     # contado em events()


def test_plugin_after_hook_observes_not_vetoes(tmp_path):
    from okami.automation.hooks import HookManager
    hookdir = tmp_path / "plugins" / "obs" / "hooks" / "after_tool"
    hookdir.mkdir(parents=True)
    (tmp_path / "plugins" / "obs" / "plugin.yaml").write_text("name: obs\n", encoding="utf-8")
    s = hookdir / "log.sh"
    s.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")    # after_* não bloqueia mesmo com exit≠0
    s.chmod(0o755)
    hm = HookManager(root=str(tmp_path))
    assert hm.fire("after_tool", {}) is True


# ── browser supervisor: CDP events → snapshot + política de diálogo ──
def test_supervisor_tracks_dialog():
    from okami.integrations.browser_supervisor import BrowserSupervisor
    sup = BrowserSupervisor()
    sup.handle_event("Page.javascriptDialogOpening", {"type": "confirm", "message": "tem certeza?"})
    snap = sup.snapshot()
    assert snap["pending_dialogs"] and snap["pending_dialogs"][0]["type"] == "confirm"
    sup.handle_event("Page.javascriptDialogClosed", {})
    assert sup.snapshot()["pending_dialogs"] == []


def test_supervisor_tracks_frame_tree():
    from okami.integrations.browser_supervisor import BrowserSupervisor
    sup = BrowserSupervisor()
    sup.handle_event("Page.frameAttached", {"frameId": "f1", "parentFrameId": "root"})
    sup.handle_event("Page.frameAttached", {"frameId": "f2", "parentFrameId": "f1"})
    assert set(sup.snapshot()["frames"]) == {"f1", "f2"}


def test_dialog_policy_decides():
    from okami.integrations.browser_supervisor import dialog_decision
    assert dialog_decision({"type": "alert"}, "auto_dismiss")["accept"] is False
    assert dialog_decision({"type": "confirm"}, "auto_accept")["accept"] is True
    assert dialog_decision({"type": "prompt"}, "must_respond")["defer"] is True   # espera o agente


# ── web dashboard + gui ──
def test_render_status_html():
    from okami.gateway.web import render_status_html
    html = render_status_html({"agent": "dev", "sessions": 3, "uptime": "2h"})
    assert "<html" in html.lower() and "dev" in html and "3" in html


def test_dashboard_route():
    from okami.gateway.web import route
    assert route("/")[0] == 200
    assert route("/healthz") == (200, "text/plain", "ok")
    assert route("/nao-existe")[0] == 404
