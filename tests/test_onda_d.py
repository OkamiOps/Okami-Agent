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


def test_dashboard_serves_app_html():
    from okami.gateway.web import route
    code, ctype, body = route("/")
    assert code == 200 and "text/html" in ctype
    assert "Okami" in body and "/api/" in body and "fetch(" in body   # app single-file faz fetch das APIs


def test_dashboard_api_endpoints_json():
    import json
    from okami.gateway.web import route
    providers = {
        "status": lambda: {"agent": "dev", "sessions": 2},
        "sessions": lambda: [{"chat_id": "c1", "turns": 3}],
        "config": lambda: {"providers": ["claude"], "env_present": ["ANTHROPIC_API_KEY"]},
        "logs": lambda: ["2026-06-16 INFO up"],
    }
    for path, key in [("/api/status", "agent"), ("/api/sessions", None), ("/api/config", "providers"), ("/api/logs", None)]:
        code, ctype, body = route(path, providers=providers)
        assert code == 200 and "json" in ctype
        data = json.loads(body)
        if key:
            assert key in data
    # endpoint sem provider → 200 com payload vazio/seguro, nunca 500
    assert route("/api/status")[0] == 200


def test_dashboard_config_never_leaks_secret_values():
    from okami.gateway.web import route
    # o provider de config deve expor NOMES de env, nunca valores — o route não inventa valores
    providers = {"config": lambda: {"env_present": ["ANTHROPIC_API_KEY"], "providers": ["claude"]}}
    body = route("/api/config", providers=providers)[2]
    assert "ANTHROPIC_API_KEY" in body and "sk-" not in body


# ── auth por token ──
def test_dashboard_token_auth_blocks_unauthorized():
    from okami.gateway.web import route
    assert route("/api/status", token="segredo", authorized=False)[0] == 401   # sem token → 401
    assert route("/api/status", token="segredo", authorized=True)[0] == 200    # com token → ok
    assert route("/api/status")[0] == 200                                       # sem token configurado → aberto (localhost)


# ── view de transcript por sessão ──
def test_dashboard_session_transcript_route():
    import json
    from okami.gateway.web import route
    providers = {"session": lambda sid: [{"role": "USER", "text": "oi"}, {"role": "AGENT", "text": "olá"}]}
    code, ctype, body = route("/api/session/c1", providers=providers)
    assert code == 200 and "json" in ctype
    assert len(json.loads(body)) == 2


# ── config-edit guardado (allowlist + secure_write) ──
def test_dashboard_config_set_allowlisted(tmp_path, monkeypatch):
    from okami.gateway import web
    written = {}
    monkeypatch.setattr(web, "_apply_config_set", lambda k, v: written.update({k: v}) or {"ok": True})
    code, _ctype, body = web.route_post("/api/config", '{"key": "approvals.mode", "value": "smart"}')
    assert code == 200 and written == {"approvals.mode": "smart"}


def test_dashboard_config_set_rejects_secret_key():
    from okami.gateway.web import route_post
    code, _ctype, body = route_post("/api/config", '{"key": "channels.telegram.token", "value": "sk-evil"}')
    assert code == 400 and "secret" in body.lower() or "segredo" in body.lower() or code == 400


def test_dashboard_config_set_rejects_non_allowlisted():
    from okami.gateway.web import route_post
    code, _c, _b = route_post("/api/config", '{"key": "qualquer.coisa", "value": "x"}')
    assert code == 400                                  # chave fora do allowlist → recusa


# ── self-hosting: bind público EXIGE token ──
def test_public_bind_requires_token():
    from okami.gateway.web import public_bind_needs_token
    assert public_bind_needs_token("0.0.0.0", None) is True       # público sem token → precisa
    assert public_bind_needs_token("0.0.0.0", "tok") is False     # público com token → ok
    assert public_bind_needs_token("127.0.0.1", None) is False    # localhost → ok sem token
    assert public_bind_needs_token("localhost", None) is False


def test_serve_dashboard_refuses_public_without_token():
    import pytest
    from okami.gateway import web
    with pytest.raises(ValueError):
        web.serve_dashboard(host="0.0.0.0", token=None)           # recusa ANTES de bindar


# ── janela nativa do desktop (pywebview) com fallback a chrome --app → browser ──
def test_pick_window_backend():
    from okami.cli.commands.basics import _pick_window_backend
    # nativo pedido + pywebview presente → webview do SO
    assert _pick_window_backend(native=True, has_webview=True, has_chrome=True) == "webview"
    # nativo pedido mas sem pywebview → cai p/ chrome --app
    assert _pick_window_backend(native=True, has_webview=False, has_chrome=True) == "chrome"
    # nativo pedido, sem webview e sem chrome → browser comum
    assert _pick_window_backend(native=True, has_webview=False, has_chrome=False) == "browser"
    # não-nativo mas app-window → chrome --app (comportamento atual)
    assert _pick_window_backend(native=False, has_webview=True, has_chrome=True) == "chrome"
