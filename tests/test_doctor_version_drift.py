"""doctor(): checagem de version-drift (WIN5) — okami.__version__ vs pyproject.toml (instalação desatualizada)."""

from __future__ import annotations

from okami.cli.commands.basics import _find_pyproject, _pyproject_version, _version_drift_warning


def test_pyproject_version_parses_project_table():
    text = '[project]\nname = "okami-agent"\nversion = "0.9.0-alpha"\ndescription = "x"\n'
    assert _pyproject_version(text) == "0.9.0-alpha"


def test_pyproject_version_none_when_missing():
    assert _pyproject_version("[project]\nname = \"x\"\n") is None
    assert _pyproject_version("") is None


def test_version_drift_warning_none_when_matching():
    assert _version_drift_warning("0.9.0-alpha", "0.9.0-alpha") is None


def test_version_drift_warning_none_when_no_pyproject():
    assert _version_drift_warning("0.9.0-alpha", None) is None


def test_version_drift_warning_flags_mismatch():
    msg = _version_drift_warning("0.9.0-alpha", "0.10.0")
    assert msg is not None
    assert "0.9.0-alpha" in msg and "0.10.0" in msg


def test_find_pyproject_prefers_cwd(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    p = _find_pyproject()
    assert p is not None and p.parent == tmp_path


def test_find_pyproject_finds_repo_root_when_run_elsewhere(tmp_path, monkeypatch):
    # cwd sem pyproject.toml → cai pro pyproject.toml da raiz do pacote instalado (repo real deste checkout)
    monkeypatch.chdir(tmp_path)
    p = _find_pyproject()
    assert p is not None and p.name == "pyproject.toml"
