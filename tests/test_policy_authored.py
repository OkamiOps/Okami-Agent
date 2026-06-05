"""Policy autorada de conformance (#P1.3): load/merge, allowlists, ingress, trust, init/check CLI."""

from __future__ import annotations

from types import SimpleNamespace

from okami.core.policy import (DEFAULT_POLICY, collect_channels, evaluate, load_policy, scaffold)


def _cfg(**over):
    base = dict(approvals={"mode": "manual"}, sandbox={}, mcp={}, gateway={}, voice={},
                providers={}, memory={}, default_provider="codex")
    base.update(over)
    return SimpleNamespace(**base)


def _pc(model="openai-codex/gpt-5.5"):
    return SimpleNamespace(model=model, tier="strong", transport="codex_oauth", ready=True,
                           api_key_env=None, api_key=None, auth="oauth_subscription")


def _levels(findings):
    return {f.check: f.level for f in findings}


def test_load_policy_default_when_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    policy, source = load_policy()
    assert source == "(default)" and policy["mcp"]["max_trust"] == "reviewed"


def test_load_policy_merges_authored(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.policy.yaml").write_text("providers:\n  allow: [codex]\n", encoding="utf-8")
    policy, source = load_policy()
    assert policy["providers"]["allow"] == ["codex"]
    assert policy["approvals"]["mode_allow"] == ["manual", "smart"]   # baseline preservada no merge


def test_provider_allowlist_violation(tmp_path):
    cfg = _cfg(providers={"codex": _pc(), "sketchy": _pc()})
    pol = {**DEFAULT_POLICY, "providers": {"allow": ["codex"]}}
    f = evaluate(cfg, pol, base_yaml=tmp_path / "none.yaml")
    assert _levels(f)["policy.providers"] == "fail"


def test_model_glob_allowlist(tmp_path):
    cfg = _cfg(providers={"codex": _pc("openai-codex/gpt-5.5"), "weird": _pc("evil/model-x")})
    pol = {**DEFAULT_POLICY, "models": {"allow": ["openai-codex/*"]}}
    f = evaluate(cfg, pol, base_yaml=tmp_path / "none.yaml")
    assert _levels(f)["policy.models"] == "fail"


def test_channel_open_ingress_fails(tmp_path):
    chans = {("(global)", "telegram"): {"token": "x", "allow_all": True}}
    f = evaluate(_cfg(), DEFAULT_POLICY, channels=chans, base_yaml=tmp_path / "none.yaml")
    assert _levels(f)["policy.channels.telegram.ingress"] == "fail"


def test_channel_allowlist_ok(tmp_path):
    chans = {("(global)", "telegram"): {"token": "x", "allow_chats": [123]}}
    f = evaluate(_cfg(), DEFAULT_POLICY, channels=chans, base_yaml=tmp_path / "none.yaml")
    assert "policy.channels.telegram.ingress" not in _levels(f)   # deny-by-default OK


def test_channel_type_not_allowed(tmp_path):
    chans = {("(global)", "discord"): {"token": "x", "allow_chats": [1]}}
    pol = {**DEFAULT_POLICY, "channels": {"allow": ["telegram"], "forbid_open_ingress": True}}
    f = evaluate(_cfg(), pol, channels=chans, base_yaml=tmp_path / "none.yaml")
    assert _levels(f)["policy.channels.discord"] == "fail"


def test_mcp_trust_ceiling(tmp_path):
    cfg = _cfg(mcp={"docs": {"trusted": True}})       # trusted > reviewed (teto) → fail (estrutura flat)
    f = evaluate(cfg, DEFAULT_POLICY, base_yaml=tmp_path / "none.yaml")
    assert _levels(f)["policy.mcp.docs"] == "fail"


def test_mcp_nested_servers_structure_detected(tmp_path):
    """#P1: a estrutura REAL é mcp.servers.<n> — antes o loop pegava ('servers',{}) e o trusted passava."""
    cfg = _cfg(mcp={"servers": {"evil": {"trusted": True}}})
    f = evaluate(cfg, DEFAULT_POLICY, base_yaml=tmp_path / "none.yaml")
    assert _levels(f)["policy.mcp.evil"] == "fail"
    assert "policy.mcp.servers" not in _levels(f)      # não confunde a chave 'servers' com um servidor


def test_lint_mcp_nested_servers(tmp_path):
    from okami.core.lint import lint_posture
    cfg = _cfg(mcp={"servers": {"evil": {"trusted": True}}})
    f = lint_posture(cfg, base_yaml=tmp_path / "none.yaml")
    assert any(x.check == "mcp.evil.trust" for x in f)


def test_approval_mode_policy(tmp_path):
    f = evaluate(_cfg(approvals={"mode": "yolo"}), DEFAULT_POLICY, base_yaml=tmp_path / "none.yaml")
    assert _levels(f)["policy.approvals"] == "fail"


def test_strict_overlay_turns_on_production_posture():
    from okami.core.policy import PRODUCTION_OVERLAY, strict_policy
    base = {**DEFAULT_POLICY}
    assert base["sandbox"]["require_isolation_on_exposed"] is False     # default dev-friendly
    strict = strict_policy(base)
    assert strict["sandbox"]["require_isolation_on_exposed"] is True    # overlay liga
    assert strict["retention"]["require"] is True
    assert "require_isolation_on_exposed" in PRODUCTION_OVERLAY["sandbox"]


def test_strict_gate_fails_exposed_without_isolation(tmp_path):
    """GA: superfície exposta sem isolamento estrito → FAIL no --strict (mas passa no default)."""
    from okami.core.policy import strict_policy
    chans = {("(global)", "telegram"): {"token": "x", "allow_chats": [1]}}
    cfg = _cfg(sandbox={})
    # default (dev): sem fail de isolamento
    dev = evaluate(cfg, DEFAULT_POLICY, channels=chans, base_yaml=tmp_path / "n.yaml")
    assert "policy.sandbox.isolation" not in _levels(dev)
    # strict (GA): exige isolamento → fail
    ga = evaluate(cfg, strict_policy(DEFAULT_POLICY), channels=chans, base_yaml=tmp_path / "n.yaml")
    assert _levels(ga)["policy.sandbox.isolation"] == "fail"
    # com require_isolation no sandbox → strict passa
    ok = evaluate(_cfg(sandbox={"require_isolation": True}), strict_policy(DEFAULT_POLICY),
                  channels=chans, base_yaml=tmp_path / "n.yaml")
    assert "policy.sandbox.isolation" not in _levels(ok)


def test_strict_cli_flag(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: codex\nproviders:\n  codex:\n    tier: strong\n    model: openai-codex/gpt-5.5\n"
        "    transport: codex_oauth\napprovals:\n  mode: manual\nchannels:\n  telegram:\n    token: x\n"
        "    allow_chats: [1]\n", encoding="utf-8")
    res = CliRunner().invoke(app, ["policy", "check", "--strict"])
    assert res.exit_code == 1 and "isolation" in res.output     # exposto sem isolamento → GA reprova
    res2 = CliRunner().invoke(app, ["policy", "show", "--strict"])
    assert "produção" in res2.output and "require_isolation_on_exposed: true" in res2.output


def test_require_isolation_on_exposed(tmp_path):
    # #P1.2: policy exige isolamento real em superfície exposta; sandbox sem strict → fail
    pol = {**DEFAULT_POLICY, "sandbox": {"require_isolation_on_exposed": True}}
    chans = {("(global)", "telegram"): {"token": "x", "allow_chats": [1]}}
    f = evaluate(_cfg(sandbox={}), pol, channels=chans, base_yaml=tmp_path / "n.yaml")
    assert _levels(f)["policy.sandbox.isolation"] == "fail"
    # com require_isolation no sandbox → conforme
    f2 = evaluate(_cfg(sandbox={"require_isolation": True}), pol, channels=chans, base_yaml=tmp_path / "n.yaml")
    assert "policy.sandbox.isolation" not in _levels(f2)


def test_project_ships_authored_policy_and_is_self_conformant():
    """O projeto VERSIONA um okami.policy.yaml real E passa na própria política (sem FAIL)."""
    from pathlib import Path as _P

    from okami.config import load_config
    from okami.core.lint import summarize
    from okami.core.policy import evaluate, load_policy
    root = _P(__file__).resolve().parent.parent
    assert (root / "okami.policy.yaml").exists(), "falta o okami.policy.yaml autorado"
    policy, source = load_policy(root / "okami.policy.yaml")
    cfg = load_config(root / "okami.yaml")
    findings = evaluate(cfg, policy, base_yaml=root / "okami.yaml")
    s = summarize(findings)
    assert s["ok"], f"o projeto não passa na própria policy: {[vars(x) for x in findings if x.level == 'fail']}"


def test_collect_channels_global_and_agent():
    raw = {"channels": {"telegram": {"token": "g"}}}
    agents = {"bot": SimpleNamespace(raw={"channels": {"slack": {"token": "s"}}})}
    ch = collect_channels(raw, agents)
    assert ("(global)", "telegram") in ch and ("bot", "slack") in ch


def test_scaffold_is_valid_yaml():
    import yaml
    parsed = yaml.safe_load(scaffold())
    assert parsed["mcp"]["max_trust"] == "reviewed" and parsed["channels"]["forbid_open_ingress"] is True


# ---------------- CLI ----------------

def test_policy_init_and_check_cli(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: codex\nproviders:\n  codex:\n    tier: strong\n    model: openai-codex/gpt-5.5\n"
        "    transport: codex_oauth\napprovals:\n  mode: manual\n", encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(app, ["policy", "init"]).exit_code == 0
    assert (tmp_path / "okami.policy.yaml").exists()
    # restringe providers a uma lista que NÃO inclui codex → check falha
    (tmp_path / "okami.policy.yaml").write_text("providers:\n  allow: [claude]\n", encoding="utf-8")
    res = runner.invoke(app, ["policy", "check", "--json"])
    assert res.exit_code == 1 and "policy.providers" in res.output
