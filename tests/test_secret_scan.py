"""Secret-scan compartilhado (CI + pytest): repo limpo + o marcador de allowlist funciona de verdade.

Os 'segredos' fake aqui são montados por concatenação ('sk-' + 'A'*30) → NUNCA aparecem como literal
contíguo no source deste arquivo, então o próprio scanner não se autoflaga.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "secret-scan.sh"
_HAS_GIT = shutil.which("git") is not None


@pytest.mark.skipif(not _SCRIPT.exists() or not _HAS_GIT, reason="precisa do script + git")
def test_repo_has_no_unallowlisted_secret():
    """O repo REAL passa no secret-scan (não deixa main vermelho)."""
    r = subprocess.run(["bash", str(_SCRIPT)], cwd=str(_ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"secret-scan vermelho:\n{r.stdout}\n{r.stderr}"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.mark.skipif(not _SCRIPT.exists() or not _HAS_GIT, reason="precisa do script + git")
def test_marker_allowlists_but_unmarked_is_caught(tmp_path):
    """Prova que `# pragma: allowlist secret` pula a linha E que vetor SEM marcador é pego (exit 1)."""
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "scripts").mkdir()
    shutil.copy(_SCRIPT, tmp_path / "scripts" / "secret-scan.sh")
    fake = "sk-" + "A" * 30                                    # montado em runtime → não vira literal no source
    # caso 1: vetor MARCADO → scanner passa
    (tmp_path / "a.py").write_text(f'K = "{fake}"  # pragma: allowlist secret\n', encoding="utf-8")
    _git(tmp_path, "add", "-A")
    r1 = subprocess.run(["bash", "scripts/secret-scan.sh"], cwd=str(tmp_path), capture_output=True, text=True)
    assert r1.returncode == 0, f"marcado deveria passar:\n{r1.stdout}\n{r1.stderr}"
    # caso 2: o MESMO vetor SEM marcador → scanner falha
    (tmp_path / "b.py").write_text(f'K = "{fake}"\n', encoding="utf-8")
    _git(tmp_path, "add", "-A")
    r2 = subprocess.run(["bash", "scripts/secret-scan.sh"], cwd=str(tmp_path), capture_output=True, text=True)
    assert r2.returncode == 1, "vetor sem marcador deveria ser pego"


@pytest.mark.skipif(not _SCRIPT.exists() or not _HAS_GIT, reason="precisa do script + git")
def test_dotenv_versioned_is_caught(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "scripts").mkdir()
    shutil.copy(_SCRIPT, tmp_path / "scripts" / "secret-scan.sh")
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A", "-f")                          # -f: força mesmo se .gitignore
    r = subprocess.run(["bash", "scripts/secret-scan.sh"], cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 1 and ".env" in (r.stdout + r.stderr)


def test_ci_uses_the_shared_script():
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts/secret-scan.sh" in ci, "a CI precisa chamar o script compartilhado"


def test_ci_policy_step_is_explicit_json():
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "okami policy check --json" in ci and "policy-conformance" in ci
