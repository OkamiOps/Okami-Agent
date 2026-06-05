"""Testes do multi-agente (§10): load, config efetiva (merge) e roteamento por bindings."""

from __future__ import annotations

import yaml

from okami.agents import Router, build_router, effective_config, load_agents


def _mk_agent(root, aid, raw):
    d = root / "agents" / aid
    d.mkdir(parents=True)
    (d / "agent.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return d


GLOBAL = {
    "default_provider": "lmstudio",
    "providers": {"lmstudio": {"model": "openai/x", "api_key": "k"},
                  "claude": {"model": "anthropic/y", "auth": "oauth_subscription", "transport": "claude_cli"}},
    "memory": {"backend": "sqlite-fts5"},
}


def test_load_agents_discovers_dirs(tmp_path, monkeypatch):
    _mk_agent(tmp_path, "suporte", {"default_provider": "claude"})
    _mk_agent(tmp_path, "dev", {})
    # projeto: okami.yaml na pasta → base = tmp_path → agents em tmp_path/agents (casa central, não CWD cru)
    (tmp_path / "okami.yaml").write_text("default_provider: lmstudio\nproviders: {lmstudio: {model: x}}\n",
                                         encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    specs = load_agents()
    assert set(specs) == {"suporte", "dev"}
    # explícito também funciona (compat)
    assert set(load_agents(tmp_path / "agents")) == {"suporte", "dev"}


def test_effective_config_merges_overrides(tmp_path):
    d = _mk_agent(tmp_path, "suporte", {"default_provider": "claude",
                                        "memory": {"backend": "holographic"}})
    from okami.agents import AgentSpec

    spec = AgentSpec("suporte", d, yaml.safe_load((d / "agent.yaml").read_text(encoding="utf-8")))
    eff = effective_config(GLOBAL, spec)
    assert eff.default_provider == "claude"                 # override do agente
    assert eff.memory["backend"] == "holographic"           # override do agente
    assert "lmstudio" in eff.providers                       # herdou do global


def test_router_tiers_exact_beats_wildcard():
    r = Router(bindings=[
        {"match": "telegram:.*", "agent": "geral"},
        {"match": "telegram:123", "agent": "suporte"},
    ], default="geral")
    assert r.route("telegram:123") == "suporte"   # exato vence o wildcard
    assert r.route("telegram:999") == "geral"      # wildcard
    assert r.route("slack:abc") == "geral"         # default


def test_build_router_collects_agent_match(tmp_path):
    from okami.agents import AgentSpec
    from pathlib import Path

    agents = {"suporte": AgentSpec("suporte", Path("."), {"match": ["telegram:42"]})}
    r = build_router({"default": "x"}, agents)
    assert r.route("telegram:42") == "suporte"
    assert r.route("desconhecido") == "x"
