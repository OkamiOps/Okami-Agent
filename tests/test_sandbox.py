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
    assert "omitido" in big.output and len(big.output) < 300        # teto de saída (head+tail) aplicado


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


def test_run_shell_per_call_timeout_override(tmp_path):
    # run_shell aceita timeout por chamada → comando sabidamente demorado pode pedir mais tempo,
    # sem mexer no default global. Aqui REDUZIMOS p/ provar o override (sleep 3 com timeout=1 → corta).
    from okami.core.tools import RunShell, ToolContext
    ctx = ToolContext(workspace=tmp_path)
    res = RunShell().run({"cmd": "sleep 3", "timeout": 1}, ctx)
    assert not res.ok and "exit=124" in res.output
    assert "process_start" in res.output and "timeout=N" in res.output   # ensina a recuperar


def test_run_shell_timeout_override_is_clamped(tmp_path, monkeypatch):
    # valor absurdo é limitado ao TETO (1800); piso de 1s; inválido → usa o default — nunca "trava pra sempre".
    import okami.core.sandbox as _sb           # run_sandboxed é importado lazy de cá dentro do run()
    from okami.core.sandbox import SandboxResult
    from okami.core.tools import RunShell, ToolContext
    seen = {}

    def spy(cmd, ws, policy):
        seen["timeout"] = policy.timeout
        return SandboxResult(0, "ok")
    monkeypatch.setattr(_sb, "run_sandboxed", spy)
    ctx = ToolContext(workspace=tmp_path)

    RunShell().run({"cmd": "echo ok", "timeout": 999999}, ctx)
    assert seen["timeout"] == RunShell._MAX_TIMEOUT       # clampado no teto (30min)
    RunShell().run({"cmd": "echo ok", "timeout": 0}, ctx)
    assert seen["timeout"] == 1                            # piso de 1s
    RunShell().run({"cmd": "echo ok", "timeout": "lixo"}, ctx)
    assert seen["timeout"] == 120                          # inválido → default da policy (120)


def test_default_shell_timeout_is_120():
    # paridade com o critério shell_ok (120s) — menos cortes espúrios em pytest/npm install.
    from okami.core.sandbox import default_policy
    assert default_policy().timeout == 120


def test_timeout_preserves_partial_output(tmp_path):
    # ANTES: subprocess.run(timeout=…) no POSIX mata o processo e DESCARTA a saída já produzida
    # (TimeoutExpired.stdout só vem populado no Windows) → "timeout (Ns): cmd" pelado, sem o que o
    # comando já tinha impresso. Popen+Timer (porte execute_code.py) preserva essa saída parcial.
    res = run_sandboxed("printf ANTES-DO-CORTE; sleep 5; printf DEPOIS-NUNCA-SAI", tmp_path,
                        SandboxPolicy(timeout=1))
    assert res.timed_out and res.returncode == 124
    assert "timeout (1s):" in res.output              # marcador de timeout continua presente
    # a saída REAL do processo (linha após o marcador) tem a parte de ANTES do kill — não é só o
    # "timeout (Ns): cmd" pelado de antes desta correção. (cmd fica ecoado na msg — não comparamos o
    # segundo marcador aqui pra não confundir "apareceu no output do processo" com "apareceu pq é
    # parte do texto do comando ecoado".)
    body = res.output.split("\n", 1)[1] if "\n" in res.output else ""
    assert "ANTES-DO-CORTE" in body


def test_timeout_with_no_output_still_reports_timeout(tmp_path):
    # comando que não imprime NADA antes do kill → sem output parcial, mas o marcador de timeout segue.
    res = run_sandboxed("sleep 5", tmp_path, SandboxPolicy(timeout=1))
    assert res.timed_out and res.returncode == 124
    assert "timeout (1s): sleep 5" in res.output
