"""Reuso de container entre comandos (pesquisa #6 item 26, paridade Hermes docker reuse).

Em vez de `docker run --rm` por comando (cold-start toda vez, estado some entre comandos), um
container long-lived por (workspace, perfil) com `docker exec`. Entrega "ambiente sobrevive entre
turnos" (o que o Modal vende como hibernação) usando só Docker LOCAL — casa com dono-único/confiável.
"""
from __future__ import annotations

from pathlib import Path

from okami.core.sandbox import SandboxPolicy, container_name, docker_exec_argv, docker_run_persistent_argv


def test_container_name_stable_per_workspace_and_mode(tmp_path):
    p = SandboxPolicy(backend="docker", mode="workspace-write")
    n1 = container_name(tmp_path, p)
    n2 = container_name(tmp_path, p)
    assert n1 == n2 and n1.startswith("okami-")        # determinístico


def test_container_name_differs_by_mode(tmp_path):
    a = container_name(tmp_path, SandboxPolicy(backend="docker", mode="workspace-write"))
    b = container_name(tmp_path, SandboxPolicy(backend="docker", mode="read-only"))
    assert a != b                                       # perfil diferente → container diferente


def test_run_persistent_argv_keeps_alive(tmp_path):
    argv = docker_run_persistent_argv(tmp_path, SandboxPolicy(backend="docker"), name="okami-x")
    assert "--rm" not in argv                           # NÃO efêmero (sobrevive ao comando)
    assert "-d" in argv                                 # detached (fica no ar)
    assert "--name" in argv and "okami-x" in argv
    # mantém o endurecimento: rede off, cap-drop, tmpfs noexec
    assert "--network" in argv and "none" in argv
    assert "--cap-drop" in argv
    assert any("noexec" in a for a in argv)


def test_exec_argv_runs_in_named_container(tmp_path):
    argv = docker_exec_argv("echo hi", "okami-x")
    assert argv[:2] == ["docker", "exec"]
    assert "okami-x" in argv
    assert argv[-1] == "echo hi" and argv[-3:-1] == ["sh", "-lc"]


def test_readonly_mode_persistent_is_ro_mount(tmp_path):
    argv = docker_run_persistent_argv(tmp_path, SandboxPolicy(backend="docker", mode="read-only"),
                                      name="okami-ro")
    ws = str(Path(tmp_path).resolve())
    assert f"{ws}:/workspace:ro" in argv
