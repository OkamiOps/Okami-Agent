"""Gateway como serviço (launchd/systemd) — renderizadores puros + paths."""

from __future__ import annotations

from pathlib import Path

from okami.gateway import service


def test_detect_platform_is_known():
    assert service.detect_platform() in ("launchd", "systemd", "unsupported")


def test_exec_argv_runs_gateway_foreground():
    assert service.exec_argv()[-2:] == ["gateway", "--foreground"]


def test_render_launchd_has_label_args_env_keepalive():
    plist = service.render_launchd(["/bin/okami", "gateway", "--foreground"],
                                   "/proj", "/h/.okami/logs/g.log", "/h/.okami")
    assert "ops.okami.gateway" in plist
    assert "<string>gateway</string>" in plist and "<string>--foreground</string>" in plist
    assert "OKAMI_HOME" in plist and "/h/.okami</string>" in plist
    assert "KeepAlive" in plist and "RunAtLoad" in plist
    assert "/proj" in plist and "/h/.okami/logs/g.log" in plist


def test_render_systemd_unit_is_valid():
    unit = service.render_systemd(["okami", "gateway", "--foreground"],
                                  "/proj", "/h/.okami/logs/g.log", "/h/.okami")
    assert "[Unit]" in unit and "[Service]" in unit and "[Install]" in unit
    assert "ExecStart=okami gateway --foreground" in unit
    assert "Environment=OKAMI_HOME=/h/.okami" in unit
    assert "Restart=on-failure" in unit and "WantedBy=default.target" in unit


def test_paths_under_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert service.launchd_plist_path() == tmp_path / "Library" / "LaunchAgents" / "ops.okami.gateway.plist"
    assert service.systemd_unit_path() == tmp_path / ".config" / "systemd" / "user" / "okami-gateway.service"


def test_systemd_argv_quotes_paths_with_spaces():
    unit = service.render_systemd(["/opt/my okami/bin/okami", "gateway", "--foreground"],
                                  "/proj", "/h/.okami/logs/g.log", "/h/.okami")
    assert 'ExecStart="/opt/my okami/bin/okami" gateway --foreground' in unit   # path com espaço entre aspas
    assert service._systemd_argv(['/x/a"b\\c']) == '"/x/a\\"b\\\\c"'            # aspas e barra escapadas


def test_gateway_files_live_in_home_not_cwd(monkeypatch, tmp_path):
    from okami.cli.commands.gateway import _gateway_files
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path / "home"))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    pid, log = _gateway_files()
    assert pid == tmp_path / "home" / "runtime" / "gateway.pid"
    assert log == tmp_path / "home" / "logs" / "gateway.log"
    assert not (work / ".okami").exists()                       # NÃO espalha estado no CWD


def test_log_path_respects_okami_home(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path / "h"))
    assert service.log_path() == tmp_path / "h" / "logs" / "gateway.log"


def test_logs_cli_reads_file(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from okami.cli import app
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path / "h"))
    log = service.log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("linha um\nlinha dois\n", encoding="utf-8")
    out = CliRunner().invoke(app, ["logs", "-n", "5"]).output
    assert "linha dois" in out
