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
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None, env=None: _ok("Already up to date."))
    ok, msg = up.git_pull(tmp_path)
    assert ok and "up to date" in msg


def test_git_pull_failure_aborts_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None, env=None: _fail("network unreachable"))
    ok, msg = up.git_pull(tmp_path)
    assert not ok and "network unreachable" in msg


def test_git_pull_failure_allow_dirty_degrades_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None, env=None: _fail("dirty tree"))
    ok, msg = up.git_pull(tmp_path, allow_dirty=True)
    assert ok and "allow-dirty" in msg or "mantendo" in msg


def test_git_pull_no_git_on_path(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: None)
    ok, msg = up.git_pull(tmp_path)
    assert not ok and "git" in msg.lower()


def test_uv_tool_install_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None, env=None: _ok("Installed okami-agent"))
    ok, msg = up.uv_tool_install(tmp_path)
    assert ok and "Installed" in msg


def test_uv_tool_install_missing_uv(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: None)
    ok, msg = up.uv_tool_install(tmp_path)
    assert not ok and "uv" in msg.lower()


def test_uv_tool_install_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None, env=None: _fail("resolution failed"))
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
    state = {"sha": "aaaaaaa"}          # SHA antes; muda depois do reset (simula commit novo do GitHub)

    def fake_run(cmd, cwd=None, env=None):
        calls.append(cmd)
        if cmd[:2] == ["git", "rev-parse"] and "HEAD" in cmd:
            return _ok(state["sha"])
        if cmd[:2] == ["git", "fetch"]:
            return _ok("")
        if cmd[:3] == ["git", "symbolic-ref", "--short"]:
            return _ok("origin/main")
        if cmd[:2] == ["git", "status"]:
            return _ok("")             # limpo
        if cmd[:3] == ["git", "reset", "--hard"]:
            state["sha"] = "bbbbbbb"    # reset moveu p/ origin/main → SHA novo
            (src / "pyproject.toml").write_text(
                '[project]\nname = "okami-agent"\nversion = "0.13.0-beta"\n', encoding="utf-8"
            )
            return _ok("HEAD is now at bbbbbbb")
        return _ok("Installed okami-agent")

    monkeypatch.setattr(up, "_run", fake_run)

    res = CliRunner().invoke(app, ["upgrade", "--yes"])
    assert res.exit_code == 0, res.output
    assert "0.11.0-beta" in res.output and "0.13.0-beta" in res.output
    assert any(c[:2] == ["git", "fetch"] for c in calls)
    assert any(c[:3] == ["git", "reset", "--hard"] for c in calls)
    assert any("tool" in c and "install" in c for c in calls)


def test_cli_upgrade_already_latest(monkeypatch, tmp_path):
    src = _managed_src(tmp_path, version="0.13.0-beta")
    monkeypatch.setattr(up, "managed_src_dir", lambda: src)
    monkeypatch.setattr(up, "in_docker", lambda: False)
    monkeypatch.setattr(up, "__version__", "0.13.0-beta", raising=False)
    monkeypatch.setattr(up.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None, env=None: _ok("Already up to date."))

    res = CliRunner().invoke(app, ["upgrade", "--yes"])
    assert res.exit_code == 0, res.output
    assert "já estava na última versão" in res.output


def test_cli_upgrade_git_pull_failure_is_reported_and_exits_nonzero(monkeypatch, tmp_path):
    src = _managed_src(tmp_path)
    monkeypatch.setattr(up, "managed_src_dir", lambda: src)
    monkeypatch.setattr(up, "in_docker", lambda: False)
    monkeypatch.setattr(up.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None, env=None: _fail("could not resolve host"))

    res = CliRunner().invoke(app, ["upgrade", "--yes"])
    assert res.exit_code != 0
    assert "could not resolve host" in res.output


def test_cli_upgrade_uv_install_failure_is_reported_and_exits_nonzero(monkeypatch, tmp_path):
    src = _managed_src(tmp_path)
    monkeypatch.setattr(up, "managed_src_dir", lambda: src)
    monkeypatch.setattr(up, "in_docker", lambda: False)
    monkeypatch.setattr(up.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(cmd, cwd=None, env=None):
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
    monkeypatch.setattr(up, "_run", lambda cmd, cwd=None, env=None: called.append(cmd) or _ok())

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


def test_tool_env_targets_okami_home_when_managed(monkeypatch, tmp_path):
    # venv sob $OKAMI_HOME (install.sh) → upgrade reinstala nos MESMOS dirs (~/.okami/{tools,bin}),
    # não no default do uv — senão a versão "não muda" (bug dos dois installs paralelos).
    home = tmp_path / ".okami"
    monkeypatch.setenv("OKAMI_HOME", str(home))
    monkeypatch.setattr(up.sys, "prefix", str(home / "tools" / "okami-agent"))
    env = up._tool_env()
    assert env["UV_TOOL_DIR"] == str(home / "tools")
    assert env["UV_TOOL_BIN_DIR"] == str(home / "bin")


def test_tool_env_uses_uv_default_when_not_under_okami_home(monkeypatch, tmp_path):
    # venv no local default do uv (~/.local/...) → NÃO força dirs; deixa o uv usar o default.
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path / ".okami"))
    monkeypatch.setattr(up.sys, "prefix", "/somewhere/.local/share/uv/tools/okami-agent")
    env = up._tool_env()
    assert "UV_TOOL_DIR" not in env
    assert "UV_TOOL_BIN_DIR" not in env


# ---------- shadow-detection: `okami` no PATH aponta pra outro binário que não o recém-instalado ----------

def test_installed_bin_path_uses_uv_tool_bin_dir_when_present(tmp_path):
    env = {"UV_TOOL_BIN_DIR": str(tmp_path / "bin")}
    assert up.installed_bin_path(env) == tmp_path / "bin" / "okami"


def test_installed_bin_path_falls_back_to_uv_default(monkeypatch):
    monkeypatch.setattr(up.Path, "home", classmethod(lambda cls: up.Path("/home/user")))
    assert up.installed_bin_path({}) == up.Path("/home/user/.local/bin/okami")


def test_shadow_warning_none_when_nothing_on_path(monkeypatch, tmp_path):
    monkeypatch.setattr(up.shutil, "which", lambda name: None)
    assert up.shadow_warning(tmp_path / "bin" / "okami") is None


def test_shadow_warning_none_when_path_resolves_to_installed_binary(monkeypatch, tmp_path):
    installed = tmp_path / "bin" / "okami"
    monkeypatch.setattr(up.shutil, "which", lambda name: str(installed))
    assert up.shadow_warning(installed) is None


def test_shadow_warning_fires_when_path_resolves_elsewhere(monkeypatch, tmp_path):
    shadow = tmp_path / "old" / "okami"
    installed = tmp_path / "bin" / "okami"
    monkeypatch.setattr(up.shutil, "which", lambda name: str(shadow))
    warning = up.shadow_warning(installed)
    assert warning is not None
    assert str(shadow) in warning
    assert str(installed) in warning
    assert f"rm -f {shadow}" in warning


def test_cli_upgrade_warns_on_shadowed_path(monkeypatch, tmp_path):
    src = _managed_src(tmp_path, version="0.11.0-beta")
    monkeypatch.setattr(up, "managed_src_dir", lambda: src)
    monkeypatch.setattr(up, "in_docker", lambda: False)
    monkeypatch.setattr(up, "__version__", "0.11.0-beta", raising=False)

    shadow_path = "/home/user/.local/bin/okami"

    def fake_which(name):
        if name == "okami":
            return shadow_path
        return f"/usr/bin/{name}"

    monkeypatch.setattr(up.shutil, "which", fake_which)
    monkeypatch.setattr(up, "installed_bin_path", lambda env=None: tmp_path / "okami-home" / "bin" / "okami")

    def fake_run(cmd, cwd=None, env=None):
        if cmd[:2] == ["git", "pull"]:
            (src / "pyproject.toml").write_text(
                '[project]\nname = "okami-agent"\nversion = "0.13.0-beta"\n', encoding="utf-8"
            )
            return _ok("Fast-forward")
        return _ok("Installed okami-agent")

    monkeypatch.setattr(up, "_run", fake_run)

    res = CliRunner().invoke(app, ["upgrade", "--yes"])
    assert res.exit_code == 0, res.output
    assert shadow_path in res.output
    assert "rm -f" in res.output


def test_uv_tool_install_usa_reinstall_nao_so_force(monkeypatch, tmp_path):
    """Regressão: `--force` sozinho reusa o build em cache → git pull de código sem bump de versão NÃO
    chegava no venv (o upgrade 'não pegava'). Tem que ser `--reinstall`."""
    from okami.cli.commands import upgrade as up
    captured = {}
    monkeypatch.setattr(up.shutil, "which", lambda _: "/usr/bin/uv")
    def _fake_run(cmd, **kw):
        captured["cmd"] = cmd
        class R: returncode = 0; stdout = "ok"; stderr = ""
        return R()
    monkeypatch.setattr(up, "_run", _fake_run)
    up.uv_tool_install(tmp_path)
    assert "--reinstall" in captured["cmd"], f"upgrade sem --reinstall: {captured['cmd']}"
