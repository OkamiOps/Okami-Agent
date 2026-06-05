"""Sandbox do run_shell: política, backend local (timeout/cap/read-only) e argv do docker."""

from __future__ import annotations

from pathlib import Path

from okami.core.sandbox import SandboxPolicy, default_policy, docker_argv, run_sandboxed


def test_policy_from_config_and_yolo():
    p = SandboxPolicy.from_config({"backend": "docker", "mode": "read-only", "timeout": 5})
    assert p.backend == "docker" and p.mode == "read-only" and p.timeout == 5 and p.network is False
    assert SandboxPolicy.from_config({"mode": "yolo"}).network is True   # yolo libera a rede
    assert default_policy().mode == "workspace-write" and default_policy().backend == "local"


def test_local_runs_and_caps_output(tmp_path):
    res = run_sandboxed("echo ola", tmp_path)
    assert res.returncode == 0 and "ola" in res.output
    big = run_sandboxed("python3 -c \"print('x' * 5000)\"", tmp_path, SandboxPolicy(max_output=100))
    assert "truncada" in big.output and len(big.output) < 300       # teto de saída aplicado


def test_local_nonzero_exit(tmp_path):
    assert run_sandboxed("exit 3", tmp_path).returncode == 3


def test_timeout(tmp_path):
    res = run_sandboxed("sleep 5", tmp_path, SandboxPolicy(timeout=1))
    assert res.timed_out and res.returncode == 124


def test_readonly_blocks_mutation_via_tool(tmp_path):
    from okami.core.tools import RunShell, ToolContext
    ctx = ToolContext(workspace=tmp_path, sandbox=SandboxPolicy(mode="read-only"))
    blocked = RunShell().run({"cmd": "mkdir nova"}, ctx)
    assert not blocked.ok and "read-only" in blocked.output and not (tmp_path / "nova").exists()
    ok = RunShell().run({"cmd": "echo oi"}, ctx)        # leitura roda normal
    assert ok.ok and "oi" in ok.output


def test_docker_argv_isolation():
    argv = docker_argv("ls", Path("/tmp/ws"), SandboxPolicy(backend="docker", mode="read-only"))
    assert argv[argv.index("--network") + 1] == "none"          # sem rede
    assert "--read-only" in argv and any(a.endswith(":ro") for a in argv)   # rootfs+workspace ro
    assert "--memory" in argv and "--pids-limit" in argv         # cgroups
    net = docker_argv("ls", Path("/tmp/ws"), SandboxPolicy(backend="docker", mode="yolo"))
    assert net[net.index("--network") + 1] == "bridge"          # yolo libera a rede
