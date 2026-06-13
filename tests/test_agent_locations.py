"""Diagnóstico de DIVERGÊNCIA de config de agente (fix do "sistema não está salvando").

base_dir() é a raiz do PROJETO se houver okami.yaml no CWD/ancestral, senão ~/.okami. Logo os
comandos de config gravam em lugares DIFERENTES dependendo de onde rodam — e o gateway (rodado da
home/serviço) lê ~/.okami/agents. Quando os dois têm agentes distintos, a config "some" da vista do
usuário. agent_locations() detecta isso pra avisar com o CAMINHO ABSOLUTO.
"""
from __future__ import annotations

from okami.home import agent_locations


def _mk_agent(d, name):
    (d / "agents" / name).mkdir(parents=True, exist_ok=True)
    (d / "agents" / name / "agent.yaml").write_text("channels: {}\n", encoding="utf-8")


def test_no_divergence_when_same_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("okami.home.base_dir", lambda: tmp_path)
    monkeypatch.setattr("okami.home.okami_home", lambda: tmp_path)
    _mk_agent(tmp_path, "minerva")
    loc = agent_locations()
    assert not loc["diverges"]
    assert loc["effective_agents"] == ["minerva"]


def test_divergence_detected(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    home = tmp_path / "home"
    proj.mkdir()
    home.mkdir()
    monkeypatch.setattr("okami.home.base_dir", lambda: proj)
    monkeypatch.setattr("okami.home.okami_home", lambda: home)
    _mk_agent(proj, "okami")       # comando rodando do projeto grava aqui
    _mk_agent(home, "minerva")     # gateway (da home) lê aqui
    loc = agent_locations()
    assert loc["diverges"]
    assert loc["effective_agents"] == ["okami"]
    assert loc["global_agents"] == ["minerva"]
    assert str(loc["effective"]).endswith("proj/agents")
    assert str(loc["global"]).endswith("home/agents")


def test_no_divergence_when_same_agents(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    home = tmp_path / "home"
    proj.mkdir()
    home.mkdir()
    monkeypatch.setattr("okami.home.base_dir", lambda: proj)
    monkeypatch.setattr("okami.home.okami_home", lambda: home)
    _mk_agent(proj, "minerva")
    _mk_agent(home, "minerva")     # MESMO agente nos dois → não confunde (mesmo nome)
    assert not agent_locations()["diverges"]


def test_empty_global_no_divergence(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    home = tmp_path / "home"
    proj.mkdir()
    home.mkdir()
    monkeypatch.setattr("okami.home.base_dir", lambda: proj)
    monkeypatch.setattr("okami.home.okami_home", lambda: home)
    _mk_agent(proj, "okami")
    assert not agent_locations()["diverges"]   # home vazia → gateway-da-home não tem conflito de fato
