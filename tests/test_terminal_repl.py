"""Terminal REPL concorrente + `okami config` interativo + prelearned files (anti-✗ na gênese).

Cobre as 3 dores reais do terminal:
  (1) digitar/responder enquanto o agente trabalha  → roteamento puro `_route_repl_line`;
  (2) `okami config` sem subcomando NÃO pede argumento (abre o painel);
  (3) sobrescrever os stubs de identidade na gênese sem o ✗ de grounding (prelearned_files).
"""

from __future__ import annotations

from typer.testing import CliRunner

from okami.cli import _route_repl_line, app

runner = CliRunner()


# ----------------------------------------------------------- (1) roteamento concorrente
def test_route_exit_and_help_anytime():
    for q in ("/exit", "exit", ":q", "/quit"):
        assert _route_repl_line(q, busy=True, pending_approval=True) == "exit"
    assert _route_repl_line("/help", busy=True, pending_approval=False) == "help"


def test_route_pending_approval_takes_priority():
    # com aprovação pendente, a próxima linha responde o go/no-go (mesmo "ocupado")
    assert _route_repl_line("/yes", busy=True, pending_approval=True) == "approval"
    assert _route_repl_line("qualquer coisa", busy=True, pending_approval=True) == "approval"


def test_route_stop_passes_through_even_busy():
    assert _route_repl_line("/stop", busy=True, pending_approval=False) == "stop"
    assert _route_repl_line("/parar", busy=True, pending_approval=False) == "stop"


def test_route_message_while_busy_queues_else_handles():
    assert _route_repl_line("faz isso", busy=True, pending_approval=False) == "queue"
    assert _route_repl_line("faz isso", busy=False, pending_approval=False) == "handle"


def test_route_pending_clarify_goes_direct_not_queued():
    # Com um clarify pendente (turno bloqueado esperando resposta), a próxima linha responde a pergunta
    # DIRETO (não vai pra fila de "ocupado", senão o turno nunca destrava).
    assert _route_repl_line("a segunda opção", busy=True, pending_clarify=True) == "clarify"
    assert _route_repl_line("2", busy=True, pending_clarify=True) == "clarify"
    # aprovação ainda tem prioridade sobre clarify (segurança antes de pergunta)
    assert _route_repl_line("x", busy=True, pending_approval=True, pending_clarify=True) == "approval"


# ----------------------------------------------------------- (2) `okami config` sem subcomando
def test_bare_config_shows_panel_without_args(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n"
        "  lmstudio: {model: openai/x, api_key: lm, tier: local}\n", encoding="utf-8")
    res = runner.invoke(app, ["config"])                  # SEM subcomando, SEM argumentos
    assert res.exit_code == 0                              # não explode pedindo "Missing command"
    assert "default_provider" in res.output               # mostrou a config efetiva
    assert "lm" not in res.output or "***" in res.output or "api_key" in res.output  # segredo mascarado


def test_config_subcommand_still_works(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text("default_provider: lmstudio\n", encoding="utf-8")
    runner.invoke(app, ["config", "set", "memory.backend", "holographic"])
    assert "holographic" in runner.invoke(app, ["config", "get", "memory.backend"]).output


def test_bare_groups_open_their_view_not_missing_command(tmp_path, monkeypatch):
    """`okami provider|agent|memory|cron|taste` SEM subcomando abrem a visão (não 'Missing command')."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: lmstudio\nproviders:\n"
        "  lmstudio: {model: openai/x, api_key: lm, tier: local}\n", encoding="utf-8")
    for grp in ("provider", "agent", "memory", "cron", "taste"):
        res = runner.invoke(app, [grp])
        assert res.exit_code == 0, f"{grp} saiu {res.exit_code}: {res.output}"
        assert "Missing command" not in res.output and "COMMAND [ARGS]" not in res.output


# ----------------------------------------------------------- (3) prelearned files (gênese sem ✗)
def test_prelearned_lets_overwrite_stub_without_reading(tmp_path):
    from okami.core.tools import ToolContext, WriteFile
    (tmp_path / "SOUL.md").write_text("# stub placeholder\n", encoding="utf-8")
    # SEM prelearned: grounding barra a sobrescrita de arquivo existente não-lido
    ctx_block = ToolContext(workspace=tmp_path)
    assert WriteFile().run({"path": "SOUL.md", "content": "novo"}, ctx_block).ok is False
    # COM prelearned (stub é placeholder NOSSO): escreve direto, sem o ✗
    ctx_ok = ToolContext(workspace=tmp_path, read_files={"SOUL.md"})
    assert WriteFile().run({"path": "SOUL.md", "content": "minha alma"}, ctx_ok).ok is True
    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == "minha alma"


def test_harness_seeds_prelearned_into_read_files(tmp_path):
    from okami.core import Task
    from okami.core.harness import Harness
    h = Harness(lambda *a, **k: "", Task(goal="oi"), tmp_path,
                prelearned_files=["SOUL.md", "VOICE.md"])
    assert {"SOUL.md", "VOICE.md"} <= h.ctx.read_files


def test_gateway_genesis_wires_prelearned_and_suppresses_identity_warning(tmp_path):
    """Na gênese o gateway passa prelearned_files (anti-✗) e some com o ⚠ aprovação de identidade."""
    from okami.channels.terminal import TerminalChannel
    from okami.core import Task, TaskState
    from okami.gateway import AgentEndpoint

    captured = {}
    seen_events = []

    def runner(cfg, ws, goal, *, approve=None, extra_context="", cancel=None,
               on_event=None, prelearned_files=None, **kw):
        captured["pre"] = prelearned_files
        captured["ctx"] = extra_context
        if on_event:                                  # identidade auto-aprovada NÃO deve emitir ⚠ na gênese
            on_event({"kind": "approval_request", "category": "identity_file", "reason": "SOUL.md"})
            on_event({"kind": "step", "tool": "write_file", "ok": True})
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "pronto"
        return t

    ch = TerminalChannel("okami")
    ep = AgentEndpoint("okami", None, str(tmp_path), ch, run_task=runner,
                       on_event=seen_events.append, spawn=lambda fn: fn())
    ep.handle("terminal", "oi")                       # ws novo → gênese
    assert "SOUL.md" in (captured["pre"] or [])       # prelearned chega no run_task
    assert "GÊNESE" in captured["ctx"]                # bloco de gênese injetado
    kinds = [(e.get("kind"), e.get("category")) for e in seen_events]
    assert ("approval_request", "identity_file") not in kinds   # ⚠ de identidade suprimido
    assert ("step", None) in kinds                    # o write em si continua visível
