"""Cobertura dos plugins nativos `google-meet` (port MÍNIMO do `google_meet` do Hermes) e `teams` (port
MÍNIMO do `teams_pipeline` do Hermes).

Ambos são reduções DE PROPÓSITO: a orquestração pesada do Hermes (Playwright/Chromium + ponte de áudio
realtime pro google_meet; webhooks do Microsoft Graph + job store durável + sinks Notion/Linear/Teams pro
teams_pipeline) não foi portada. O que este port garante é a SUPERFÍCIE — as tools registram, aparecem no
catálogo do runner, e ao serem chamadas devolvem uma mensagem clara do que falta (não uma exceção, não um
`ok=True` fingindo sucesso).

Segue o padrão de tests/test_plugin_git_context.py: descoberta via `plugin_roots()` +
`discover_plugins()`, e `register(ctx)` rodando sem explodir via `load_plugin_tools`.
"""
from __future__ import annotations

from okami.plugins import discover_plugins, load_plugin_tools, plugin_roots


def _discovered_plugin_names() -> set:
    return {p.name for p in discover_plugins(plugin_roots())}


def _tools() -> dict:
    return load_plugin_tools(discover_plugins(plugin_roots()))


# ── descoberta: os dois plugins nativos aparecem via plugin_roots() ──
def test_google_meet_and_teams_discovered_by_plugin_loader():
    names = _discovered_plugin_names()
    assert "google-meet" in names
    assert "teams" in names


# ── google-meet: register(ctx) contribui as 4 tools sem explodir ──
def test_google_meet_registers_tools_without_error():
    tools = _tools()
    for name in ("meet_join", "meet_status", "meet_transcript", "meet_leave"):
        assert name in tools, f"tool {name} não foi registrada pelo plugin google-meet"


def test_google_meet_did_not_port_realtime_speak_tool():
    """meet_say (falar na call em tempo real) depende da ponte de áudio realtime — não portada; a
    ausência da tool é intencional (documentada no plugin.yaml/register.py), não um esquecimento."""
    tools = _tools()
    assert "meet_say" not in tools


def test_meet_join_validates_url_before_reporting_gap():
    tools = _tools()
    join = tools["meet_join"]
    bad = join.run({"url": ""}, None)
    assert bad.ok is False
    assert "url" in bad.output.lower()

    wrong_host = join.run({"url": "https://zoom.us/j/12345"}, None)
    assert wrong_host.ok is False
    assert "meet.google.com" in wrong_host.output


def test_meet_join_reports_missing_orchestration_for_valid_url():
    tools = _tools()
    join = tools["meet_join"]
    result = join.run({"url": "https://meet.google.com/abc-defg-hij"}, None)
    assert result.ok is False
    # honesto sobre o que falta, não uma exceção genérica nem um "sucesso" fingido
    assert "playwright" in result.output.lower()
    assert "hermes-agent/plugins/google_meet" in result.output


def test_meet_status_transcript_leave_report_missing_orchestration():
    tools = _tools()
    for name in ("meet_status", "meet_transcript", "meet_leave"):
        result = tools[name].run({}, None)
        assert result.ok is False
        assert "playwright" in result.output.lower()


# ── teams: register(ctx) contribui as 2 tools sem explodir ──
def test_teams_registers_tools_without_error():
    tools = _tools()
    assert "teams_pipeline_status" in tools
    assert "teams_meeting_summary" in tools


def test_teams_pipeline_status_reports_missing_graph_credentials(monkeypatch):
    monkeypatch.delenv("TEAMS_GRAPH_TENANT_ID", raising=False)
    monkeypatch.delenv("TEAMS_GRAPH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TEAMS_GRAPH_CLIENT_SECRET", raising=False)
    tools = _tools()
    result = tools["teams_pipeline_status"].run({}, None)
    assert result.ok is True                      # é diagnóstico, não uma falha
    assert "TEAMS_GRAPH_TENANT_ID" in result.output
    assert "TEAMS_GRAPH_CLIENT_ID" in result.output
    assert "TEAMS_GRAPH_CLIENT_SECRET" in result.output


def test_teams_pipeline_status_recognizes_present_graph_credentials(monkeypatch):
    monkeypatch.setenv("TEAMS_GRAPH_TENANT_ID", "t")
    monkeypatch.setenv("TEAMS_GRAPH_CLIENT_ID", "c")
    monkeypatch.setenv("TEAMS_GRAPH_CLIENT_SECRET", "s")
    tools = _tools()
    result = tools["teams_pipeline_status"].run({}, None)
    assert result.ok is True
    assert "ausentes" not in result.output.lower()


def test_teams_meeting_summary_requires_meeting_ref():
    tools = _tools()
    summary = tools["teams_meeting_summary"]
    bad = summary.run({}, None)
    assert bad.ok is False
    assert "meeting_ref" in bad.output


def test_teams_meeting_summary_reports_missing_pipeline_for_valid_ref():
    tools = _tools()
    summary = tools["teams_meeting_summary"]
    result = summary.run({"meeting_ref": "https://teams.microsoft.com/l/meetup-join/abc"}, None)
    assert result.ok is False
    assert "hermes-agent/plugins/teams_pipeline" in result.output


# ── nenhum plugin novo derruba o carregamento do restante da suíte de plugins nativos ──
def test_all_builtin_plugins_still_discover_and_register_cleanly():
    plugins = discover_plugins(plugin_roots())
    names = {p.name for p in plugins}
    for expected in ("security-guidance", "disk-cleanup", "usage-observer", "git-context",
                      "google-meet", "teams"):
        assert expected in names
    # não deve explodir mesmo coletando tools de TODOS os plugins nativos numa passada só
    tools = load_plugin_tools(plugins)
    assert isinstance(tools, dict)
