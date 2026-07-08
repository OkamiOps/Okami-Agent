"""`okami upgrade` — atualiza o checkout gerenciado (~/.okami/src) via git pull + `uv tool install
--force`, reportando versão_antiga → versão_nova. Mocka subprocess (git/uv) e detecção de
Docker — nunca toca o disco real fora de tmp_path nem chama uv/git de verdade."""
from __future__ import annotations

import subprocess

from typer.testing import CliRunner

from okami.cli._app import app
from okami.cli.commands import upgrade as up


def _ok(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _fail(stderr: str = "boom") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


def _managed_src(tmp_path, version="0.11.0-beta"):
    src = tmp_path / "src"
    (src / ".git").mkdir(parents=True)
    (src / "pyproject.toml").write_text(
        f'[project]\nname = "okami-agent"\nversion = "{version}"\n', encoding="utf-8"
    )
    return src


# ---------- unit-level: detecção de tipo de install ----------

def test_detect_install_kind_docker(monkeypatch, tmp_path):
    monkeypatch.setattr(up, "in_docker", lambda: True)
    assert up.detect_install_kind(_managed_src(tmp_path)) == "docker"


def test_detect_install_kind_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(up, "in_docker", lambda: False)
    assert up.detect_install_kind(tmp_path / "nope") == "missing"


def test_detect_install_kind_dev_local(monkeypatch, tmp_path):
    monkeypatch.setattr(up, "in_docker", lambda: False)
    src = tmp_path / "src"
    src.mkdir()  # sem .git → não é o checkout gerenciado
    assert up.detect_install_kind(src) == "dev-local"


def test_detect_install_kind_managed(monkeypatch, tmp_path):
    monkeypatch.setattr(up, "in_docker", lambda: False)
    assert up.detect_install_kind(_managed_src(tmp_path)) == "managed"


def test_new_version_from_src_reads_pyproject(tmp_path):
    src = _managed_src(tmp_path, version="0.13.0-beta")
    assert up.new_version_from_src(src) == "0.13.0-beta"


def test_new_version_from_src_none_when_missing(tmp_path):
    assert up.new_version_from_src(tmp_path / "ghost") is None


# ---------- git_pull / uv_tool_install: subprocess mockado ----------

def test_git_pull_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None: _ok("Already up to date."))
    ok, msg = up.git_pull(tmp_path)
    assert ok and "up to date" in msg


def test_git_pull_failure_aborts_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None: _fail("network unreachable"))
    ok, msg = up.git_pull(tmp_path)
    assert not ok and "network unreachable" in msg


def test_git_pull_failure_allow_dirty_degrades_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None: _fail("dirty tree"))
    ok, msg = up.git_pull(tmp_path, allow_dirty=True)
    assert ok and "allow-dirty" in msg or "mantendo" in msg


def test_git_pull_no_git_on_path(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: None)
    ok, msg = up.git_pull(tmp_path)
    assert not ok and "git" in msg.lower()


def test_uv_tool_install_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None: _ok("Installed okami-agent"))
    ok, msg = up.uv_tool_install(tmp_path)
    assert ok and "Installed" in msg


def test_uv_tool_install_missing_uv(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: None)
    ok, msg = up.uv_tool_install(tmp_path)
    assert not ok and "uv" in msg.lower()


def test_uv_tool_install_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None: _fail("resolution failed"))
    ok, msg = up.uv_tool_install(tmp_path)
    assert not ok and "resolution failed" in msg


# ---------- CLI: `okami upgrade` end-to-end (subprocess + install-kind mockados) ----------

def test_cli_upgrade_reports_old_to_new_version(monkeypatch, tmp_path):
    src = _managed_src(tmp_path, version="0.11.0-beta")
    monkeypatch.setattr(up, "managed_src_dir", lambda: src)
    monkeypatch.setattr(up, "in_docker", lambda: False)
    monkeypatch.setattr(up, "__version__", "0.11.0-beta", raising=False)
    monkeypatch.setattr(up.shutil, "which", lambda name: f"/usr/bin/{name}")

    calls = []

    def fake_run(cmd, cwd=None):
        calls.append(cmd)
        if cmd[:2] == ["git", "pull"]:
            # simula o pull trazendo o pyproject.toml novo pro disco
            (src / "pyproject.toml").write_text(
                '[project]\nname = "okami-agent"\nversion = "0.13.0-beta"\n', encoding="utf-8"
            )
            return _ok("Fast-forward")
        return _ok("Installed okami-agent")

    monkeypatch.setattr(up, "_run", fake_run)

    res = CliRunner().invoke(app, ["upgrade", "--yes"])
    assert res.exit_code == 0, res.output
    assert "0.11.0-beta" in res.output and "0.13.0-beta" in res.output
    assert any(c[:2] == ["git", "pull"] for c in calls)
    assert any("tool" in c and "install" in c for c in calls)


def test_cli_upgrade_already_latest(monkeypatch, tmp_path):
    src = _managed_src(tmp_path, version="0.13.0-beta")
    monkeypatch.setattr(up, "managed_src_dir", lambda: src)
    monkeypatch.setattr(up, "in_docker", lambda: False)
    monkeypatch.setattr(up, "__version__", "0.13.0-beta", raising=False)
    monkeypatch.setattr(up.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None: _ok("Already up to date."))

    res = CliRunner().invoke(app, ["upgrade", "--yes"])
    assert res.exit_code == 0, res.output
    assert "já estava na última versão" in res.output


def test_cli_upgrade_git_pull_failure_is_reported_and_exits_nonzero(monkeypatch, tmp_path):
    src = _managed_src(tmp_path)
    monkeypatch.setattr(up, "managed_src_dir", lambda: src)
    monkeypatch.setattr(up, "in_docker", lambda: False)
    monkeypatch.setattr(up.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None: _fail("could not resolve host"))

    res = CliRunner().invoke(app, ["upgrade", "--yes"])
    assert res.exit_code != 0
    assert "could not resolve host" in res.output


def test_cli_upgrade_uv_install_failure_is_reported_and_exits_nonzero(monkeypatch, tmp_path):
    src = _managed_src(tmp_path)
    monkeypatch.setattr(up, "managed_src_dir", lambda: src)
    monkeypatch.setattr(up, "in_docker", lambda: False)
    monkeypatch.setattr(up.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(cmd, cwd=None):
        if cmd[:2] == ["git", "pull"]:
            return _ok("Already up to date.")
        return _fail("no space left on device")

    monkeypatch.setattr(up, "_run", fake_run)

    res = CliRunner().invoke(app, ["upgrade", "--yes"])
    assert res.exit_code != 0
    assert "no space left on device" in res.output


def test_cli_upgrade_docker_refuses_with_guidance(monkeypatch, tmp_path):
    monkeypatch.setattr(up, "in_docker", lambda: True)
    res = CliRunner().invoke(app, ["upgrade", "--yes"])
    assert res.exit_code != 0
    assert "docker pull" in res.output.lower() or "docker-build" in res.output.lower() or "make docker-build" in res.output.lower()


def test_cli_upgrade_missing_install_points_at_installer(monkeypatch, tmp_path):
    monkeypatch.setattr(up, "in_docker", lambda: False)
    monkeypatch.setattr(up, "managed_src_dir", lambda: tmp_path / "does-not-exist")
    res = CliRunner().invoke(app, ["upgrade", "--yes"])
    assert res.exit_code != 0
    assert "install.sh" in res.output


def test_cli_upgrade_dev_local_refuses_and_suggests_manual_update(monkeypatch, tmp_path):
    monkeypatch.setattr(up, "in_docker", lambda: False)
    src = tmp_path / "src"
    src.mkdir()  # sem .git
    monkeypatch.setattr(up, "managed_src_dir", lambda: src)
    res = CliRunner().invoke(app, ["upgrade", "--yes"])
    assert res.exit_code != 0
    assert "git pull" in res.output and "uv sync" in res.output


def test_cli_upgrade_check_flag_reports_current_version_without_mutating(monkeypatch, tmp_path):
    src = _managed_src(tmp_path, version="0.13.0-beta")
    monkeypatch.setattr(up, "managed_src_dir", lambda: src)
    monkeypatch.setattr(up, "in_docker", lambda: False)
    monkeypatch.setattr(up, "__version__", "0.13.0-beta", raising=False)

    called = []
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None: called.append(cmd) or _ok())

    res = CliRunner().invoke(app, ["upgrade", "--check"])
    assert res.exit_code == 0
    assert "0.13.0-beta" in res.output
    assert called == []  # --check nunca chama git/uv


def test_in_docker_detects_dockerenv_marker(tmp_path, monkeypatch):
    marker = tmp_path / ".dockerenv"
    marker.write_text("", encoding="utf-8")
    monkeypatch.setattr(up, "Path", up.Path)  # sanity: Path segue sendo pathlib.Path
    real_path = up.Path

    def fake_path(p):
        if str(p) == "/.dockerenv":
            return marker
        return real_path(p)

    monkeypatch.setattr(up, "Path", fake_path)
    assert up.in_docker() is True


def test_in_docker_false_without_markers(monkeypatch):
    monkeypatch.setattr(up.Path, "exists", lambda self: False)
    monkeypatch.setattr(
        up.Path, "read_text", lambda self, **kw: (_ for _ in ()).throw(OSError())
    )
    assert up.in_docker() is False
