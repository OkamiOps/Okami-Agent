"""Release-readiness / strict-freshness: postura versionada conforme E verificada no HEAD."""

from __future__ import annotations

from typer.testing import CliRunner

from okami.cli import app
from okami.core.readiness import Readiness, WorkflowRun, committed_strict

runner = CliRunner()

HEAD = "a" * 40
OLD = "b" * 40


def _run(sha=HEAD, conclusion="success", status="completed", artifact_ok=None):
    return WorkflowRun(conclusion=conclusion, head_sha=sha, status=status, artifact_ok=artifact_ok)


def test_verdict_ready():
    r = Readiness(head=HEAD, local_strict_ok=True, ci=_run(HEAD), strict=_run(HEAD))
    assert r.verdict == "ready"
    assert r.signals_ok()


def test_verdict_stale_when_head_moved():
    # strict passou, mas no SHA ANTERIOR → HEAD andou → STALE (a regra de frescura do usuário).
    r = Readiness(head=HEAD, local_strict_ok=True, ci=_run(HEAD), strict=_run(OLD))
    assert r.verdict == "stale"
    assert r.strict_head_match is False
    assert r.ci_head_match is True


def test_verdict_not_ready_when_committed_posture_fails():
    # config versionada reprova strict → CI nenhum salva.
    r = Readiness(head=HEAD, local_strict_ok=False, ci=_run(HEAD), strict=_run(HEAD))
    assert r.verdict == "not_ready"


def test_verdict_not_ready_on_ci_failure():
    r = Readiness(head=HEAD, local_strict_ok=True, ci=_run(HEAD, conclusion="failure"), strict=_run(HEAD))
    assert r.verdict == "not_ready"
    assert r.ci_green is False


def test_verdict_not_ready_on_strict_artifact_fail():
    r = Readiness(head=HEAD, local_strict_ok=True, ci=_run(HEAD), strict=_run(HEAD, artifact_ok=False))
    assert r.verdict == "not_ready"


def test_verdict_unknown_offline():
    r = Readiness(head=HEAD, local_strict_ok=True, ci=None, strict=None)
    assert r.verdict == "unknown"
    assert r.ci_green is None and r.strict_head_match is None


def test_in_progress_run_is_not_green():
    r = Readiness(head=HEAD, local_strict_ok=True,
                  ci=_run(HEAD, conclusion=None, status="in_progress"), strict=_run(HEAD))
    assert r.ci_green is None                 # em andamento ≠ verde
    assert r.verdict == "unknown"


def test_committed_posture_passes_strict():
    # A postura VERSIONADA do repo (ignorando agents/ local) DEVE passar strict — senão GA está bloqueado.
    ok, summary, source = committed_strict()
    assert ok is True, f"postura versionada reprova strict: {summary}"
    assert summary["counts"]["fail"] == 0


def test_cli_no_gh_offline_local_only():
    out = runner.invoke(app, ["readiness", "--no-gh", "--json"])
    assert out.exit_code == 1                  # unknown (sem CI) → exit≠0
    assert '"strict_green": true' in out.output
    assert '"verdict": "unknown"' in out.output


def test_cli_human_render_no_gh():
    out = runner.invoke(app, ["readiness", "--no-gh"])
    assert "readiness" in out.output and "strict green" in out.output
