"""CI security é GATE, não informativo (#P1.5) — trava p/ não regredir p/ `|| true`."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_CI = _ROOT / ".github" / "workflows" / "ci.yml"


def _security_steps():
    text = _CI.read_text(encoding="utf-8")
    sec = text.split("security:", 1)[1] if "security:" in text else ""
    return [ln.strip() for ln in sec.splitlines()]


@pytest.mark.skipif(not _CI.exists(), reason="ci.yml ausente")
def test_ruff_is_a_gate():
    lines = _security_steps()
    ruff = [ln for ln in lines if "ruff check" in ln]
    assert ruff, "faltou o step de ruff"
    assert all("|| true" not in ln for ln in ruff), "ruff não pode ser informativo (|| true)"


@pytest.mark.skipif(not _CI.exists(), reason="ci.yml ausente")
def test_bandit_high_is_a_gate():
    lines = _security_steps()
    gate = [ln for ln in lines if "bandit" in ln and "severity-level high" in ln]
    assert gate, "faltou o gate de bandit HIGH"
    assert all("|| true" not in ln for ln in gate), "o gate HIGH do bandit não pode ter || true"


@pytest.mark.skipif(not _CI.exists(), reason="ci.yml ausente")
def test_pip_audit_is_a_gate():
    lines = _security_steps()
    audit = [ln for ln in lines if "pip-audit -r" in ln]
    assert audit and all("|| true" not in ln for ln in audit), "pip-audit precisa ser gate"


@pytest.mark.skipif(not _CI.exists(), reason="ci.yml ausente")
def test_no_informative_marker_left():
    assert "Informativo por enquanto" not in _CI.read_text(encoding="utf-8")


@pytest.mark.skipif(not _CI.exists(), reason="ci.yml ausente")
def test_policy_conformance_is_a_gate():
    text = _CI.read_text(encoding="utf-8")
    gate = [ln for ln in text.splitlines() if "okami policy check" in ln]
    assert gate and all("|| true" not in ln for ln in gate), "policy check precisa ser gate"


@pytest.mark.skipif(not _CI.exists(), reason="ci.yml ausente")
def test_semgrep_is_a_gate():
    lines = _security_steps()
    sg = [ln for ln in lines if "semgrep scan" in ln]
    assert sg, "faltou o gate de Semgrep"
    assert all("|| true" not in ln for ln in sg), "Semgrep não pode ser informativo (|| true)"
    assert any("--error" in ln for ln in sg), "Semgrep precisa de --error p/ falar como gate"


def test_codeql_removed_needs_ghas():
    # CodeQL exige GHAS (repo privado não tem) → removido em favor do Semgrep in-runner
    assert not (_ROOT / ".github" / "workflows" / "codeql.yml").exists()
