"""tmpfs noexec no backend docker (pesquisa #6 item 25, endurecimento Hermes docker.py).

/tmp, /var/tmp, /run como tmpfs noexec,nosuid corta o vetor clássico "dropa binário em /tmp e
executa". Poucas flags no docker_argv; o workspace montado segue gravável (escrita real vai pra lá).
"""
from __future__ import annotations

from pathlib import Path

from okami.core.sandbox import SandboxPolicy, docker_argv


def _tmpfs_specs(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "--tmpfs"]


def test_tmpfs_mounts_present(tmp_path):
    argv = docker_argv("echo hi", tmp_path, SandboxPolicy(backend="docker"))
    specs = _tmpfs_specs(argv)
    mounts = {s.split(":")[0] for s in specs}
    assert {"/tmp", "/var/tmp", "/run"} <= mounts


def test_tmpfs_is_noexec_nosuid(tmp_path):
    argv = docker_argv("echo hi", tmp_path, SandboxPolicy(backend="docker"))
    for spec in _tmpfs_specs(argv):
        opts = spec.split(":", 1)[1] if ":" in spec else ""
        assert "noexec" in opts and "nosuid" in opts


def test_workspace_still_writable(tmp_path):
    # endurecer /tmp não pode tornar o workspace read-only (escrita real do agente vai pro workspace)
    argv = docker_argv("echo hi", tmp_path, SandboxPolicy(backend="docker"))
    ws = str(Path(tmp_path).resolve())
    vol = next(argv[i + 1] for i, a in enumerate(argv) if a == "-v")
    assert vol == f"{ws}:/workspace"          # sem :ro no modo workspace-write


def test_readonly_mode_keeps_tmpfs_and_ro_root(tmp_path):
    argv = docker_argv("echo hi", tmp_path, SandboxPolicy(backend="docker", mode="read-only"))
    assert "--read-only" in argv               # rootfs ro segue
    assert _tmpfs_specs(argv)                   # mas /tmp tmpfs continua (senão nada escreve nem em /tmp)
