"""Lint de postura (#12): doctor --lint / policy check / status --json — conformance estilo OpenClaw."""

from __future__ import annotations

from types import SimpleNamespace

from okami.core.lint import _scan_secret_literals, lint_posture, summarize


def _cfg(**over):
    base = dict(approvals={"mode": "manual"}, sandbox={"backend": "local"}, mcp={}, gateway={}, voice={},
                providers={}, memory={})
    base.update(over)
    return SimpleNamespace(**base)


def _levels(findings):
    return {f.check: f.level for f in findings}


def test_yolo_mode_fails(tmp_path):
    f = lint_posture(_cfg(approvals={"mode": "yolo"}), base_yaml=tmp_path / "none.yaml")
    assert _levels(f)["approvals.mode"] == "fail"


def test_off_mode_warns(tmp_path):
    f = lint_posture(_cfg(approvals={"mode": "off"}), base_yaml=tmp_path / "none.yaml")
    assert _levels(f)["approvals.mode"] == "warn"


def test_manual_mode_passes(tmp_path):
    f = lint_posture(_cfg(), base_yaml=tmp_path / "none.yaml")
    assert _levels(f)["approvals.mode"] == "pass"


def test_secret_literal_in_base_yaml_fails(tmp_path):
    base = tmp_path / "okami.yaml"
    base.write_text("providers:\n  openai:\n    api_key: sk-hardcoded-literal\n", encoding="utf-8")
    f = lint_posture(_cfg(), base_yaml=base)
    assert _levels(f)["secrets.in_yaml"] == "fail"


def test_secret_env_ref_in_base_yaml_passes(tmp_path):
    base = tmp_path / "okami.yaml"
    base.write_text("providers:\n  openai:\n    api_key: ${OPENAI_API_KEY}\n", encoding="utf-8")
    f = lint_posture(_cfg(), base_yaml=base)
    assert _levels(f)["secrets.in_yaml"] == "pass"


def test_scan_secret_literals_helper():
    node = {"providers": {"x": {"api_key": "literal"}}, "channels": {"t": {"token": "${T}"}}, "ok": "plain"}
    leaks = _scan_secret_literals(node)
    assert "providers.x.api_key" in leaks and "channels.t.token" not in leaks


def test_sandbox_local_with_gateway_warns(tmp_path):
    f = lint_posture(_cfg(sandbox={"backend": "local"}, gateway={"host": "127.0.0.1"}),
                     base_yaml=tmp_path / "n.yaml")
    assert _levels(f)["sandbox.backend"] == "warn"


def test_mcp_trusted_warns(tmp_path):
    f = lint_posture(_cfg(mcp={"docs": {"trusted": True}}), base_yaml=tmp_path / "n.yaml")
    assert _levels(f)["mcp.docs.trust"] == "warn"


def test_mcp_insecure_remote_fails(tmp_path):
    f = lint_posture(_cfg(mcp={"x": {"url": "http://evil.com", "insecure": True}}), base_yaml=tmp_path / "n.yaml")
    assert _levels(f)["mcp.x.url"] == "fail"


def test_gateway_public_bind_without_token_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("OKAMI_API_TOKEN", raising=False)
    f = lint_posture(_cfg(gateway={"host": "0.0.0.0"}), base_yaml=tmp_path / "n.yaml")
    assert _levels(f)["gateway.exposure"] == "fail"


def test_summarize_worst_and_ok():
    from okami.core.lint import Finding
    s = summarize([Finding("a", "pass", ""), Finding("b", "warn", "")])
    assert s["worst"] == "warn" and s["ok"] is True
    s2 = summarize([Finding("c", "fail", "")])
    assert s2["worst"] == "fail" and s2["ok"] is False


# ---------------- CLI wiring ----------------

def test_doctor_lint_cli(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: p\nproviders:\n  p:\n    tier: free\n    model: m\napprovals:\n  mode: yolo\n",
        encoding="utf-8")
    res = CliRunner().invoke(app, ["doctor", "--lint"])
    assert res.exit_code == 1 and "approvals.mode" in res.output     # yolo → falha


def test_policy_check_cli_json(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: p\nproviders:\n  p:\n    tier: free\n    model: m\napprovals:\n  mode: manual\n",
        encoding="utf-8")
    res = CliRunner().invoke(app, ["policy", "check", "--json"])
    assert res.exit_code == 0 and '"ok": true' in res.output.lower().replace(" ", " ")


def test_status_json_cli(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.chdir(tmp_path)
    (tmp_path / "okami.yaml").write_text(
        "default_provider: p\nproviders:\n  p:\n    tier: free\n    model: m\n", encoding="utf-8")
    res = CliRunner().invoke(app, ["status", "--json"])
    assert res.exit_code == 0 and '"default_provider"' in res.output and '"lint"' in res.output
