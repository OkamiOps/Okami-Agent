"""`okami prompt-size` (WIN4, espírito hermes_cli/prompt_size.py): diagnóstico de tamanho do system
prompt por seção — não chama provider nenhum, só monta o MESMO texto que o harness mandaria."""
from __future__ import annotations

from typer.testing import CliRunner

from okami.cli import app

runner = CliRunner()

_YAML = ("default_provider: lmstudio\nproviders:\n"
         "  lmstudio: {model: openai/x, api_key: lm, tier: local}\n")


def test_prompt_size_runs_and_reports_sane_numbers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(_YAML, encoding="utf-8")
    res = runner.invoke(app, ["prompt-size"])
    assert res.exit_code == 0, res.output
    assert "tools" in res.output.lower()
    assert "TOTAL" in res.output


def test_prompt_size_json_has_positive_total_and_sections(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(_YAML, encoding="utf-8")
    res = runner.invoke(app, ["prompt-size", "--json"])
    assert res.exit_code == 0, res.output
    import json as _json
    data = _json.loads(res.output)
    assert data["total"]["chars"] > 0
    assert data["total"]["tokens"] == data["total"]["chars"] // 4
    assert data["tool_count"] > 0
    assert len(data["sections"]) >= 3
    for s in data["sections"]:
        assert s["chars"] >= 0
        assert s["tokens"] == s["chars"] // 4
    # a soma das seções cabe DENTRO do total (não é maior — cada seção é uma FATIA do prompt final)
    assert sum(s["chars"] for s in data["sections"]) <= data["total"]["chars"]


def test_prompt_size_unknown_provider_errors_cleanly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(_YAML, encoding="utf-8")
    res = runner.invoke(app, ["prompt-size", "--provider", "nao-existe"])
    assert res.exit_code == 1
    assert "não encontrado" in res.output or "not found" in res.output.lower()


def test_prompt_size_sections_function_matches_full_prompt_length(tmp_path):
    """Unidade (sem CLI): a função devolve o MESMO total que build_system_prompt produziria."""
    from okami.core import Task, default_registry
    from okami.core.harness.prompt import build_system_prompt, prompt_size_sections

    registry = default_registry()
    task = Task(goal="diagnóstico", exit_criteria=[])
    data = prompt_size_sections(task, registry, "algum core block", workspace=tmp_path,
                                surface="cli", model="gpt-5", native=False)
    full = build_system_prompt(task, registry, "algum core block", workspace=tmp_path,
                               surface="cli", model="gpt-5", native=False)
    assert data["total"]["chars"] == len(full)
