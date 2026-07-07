"""WIN #3: `okami run` (Fase 0 — ida-e-volta crua, SEM registry de tools nem loop de execução).

Cobre:
  1. _run_system_prompt SEMPRE inclui o aviso "sem ferramentas" (mesmo com --system custom) —
     sem isso o modelo (treinado em dados agentic) finge ter tools e alucina tool_call/listagens
     de arquivo como se fossem reais (achado via E2E).
  2. A saída exibida (--no-stream e streaming) tem <think>/reasoning removido antes de chegar
     na tela — reusa strip_think_blocks (mesmo helper do harness, paridade).
"""

from __future__ import annotations

from typer.testing import CliRunner

from okami.cli.commands.basics import _run_system_prompt


def test_no_tools_notice_present_by_default():
    sysprompt = _run_system_prompt(None)
    assert "ferramentas" in sysprompt.lower()
    assert "não" in sysprompt.lower()


def test_no_tools_notice_survives_custom_system():
    sysprompt = _run_system_prompt("Você é um assistente de culinária.")
    assert "culinária" in sysprompt
    assert "ferramentas" in sysprompt.lower()   # aviso nunca é sobrescrito


def test_no_tools_notice_handles_blank_system():
    assert _run_system_prompt("   ").strip() == _run_system_prompt(None).strip()


def _cli_env(monkeypatch, *, stream_pieces=None, complete_out=None):
    """Monkeypatcha _load()/provider() e prov.complete/stream_complete p/ rodar `okami run`
    sem rede nem config real."""
    from types import SimpleNamespace
    import okami.cli.commands.basics as basics
    from okami.llm import providers as prov

    pc = SimpleNamespace(name="fake", model="fake-model", tier="local", ready=True, api_key_env="X")
    cfg = SimpleNamespace(provider=lambda *a, **k: pc)
    monkeypatch.setattr(basics, "_load", lambda: cfg)

    captured = {}

    def fake_complete(cfg_, prompt, *, provider=None, system=None, model=None):
        captured["system"] = system
        return complete_out or "ok"

    def fake_stream(cfg_, prompt, *, provider=None, system=None, model=None):
        captured["system"] = system
        for p in (stream_pieces or ["ok"]):
            yield p

    monkeypatch.setattr(prov, "complete", fake_complete)
    monkeypatch.setattr(prov, "stream_complete", fake_stream)
    return captured


def test_run_no_stream_strips_think_and_sends_no_tools_system(monkeypatch):
    from okami.cli import app
    captured = _cli_env(monkeypatch, complete_out="<think>rascunho interno</think>resposta final")

    result = CliRunner().invoke(app, ["run", "oi", "--no-stream"])

    assert result.exit_code == 0
    assert "rascunho interno" not in result.stdout
    assert "resposta final" in result.stdout
    assert "ferramentas" in captured["system"].lower()


def test_run_streaming_strips_think_across_chunks(monkeypatch):
    from okami.cli import app
    # a tag <think> chega partida em pedaços — só forma a tag completa depois de vários chunks.
    captured = _cli_env(monkeypatch, stream_pieces=["<thi", "nk>segredo</thi", "nk>", "resposta"])

    result = CliRunner().invoke(app, ["run", "oi"])

    assert result.exit_code == 0
    assert "segredo" not in result.stdout
    assert "resposta" in result.stdout
    assert "ferramentas" in captured["system"].lower()
