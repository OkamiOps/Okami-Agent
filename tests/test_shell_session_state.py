"""run_shell (backend local) ficava STATELESS entre chamadas — `cd sub` ou `export FOO=bar` numa
chamada sumiam na próxima (files.py dizia isso na cara: "cada chamada roda do ZERO"). Portamos o
padrão do Hermes: cwd e env exportado PERSISTEM por conversa (session_key), o jail do workspace
continua valendo (cd pra fora é recusado), e o marcador interno nunca vaza pro modelo.
"""
from __future__ import annotations

from okami.core.sandbox import default_policy, reset_session, run_sandboxed
from okami.core.tools import ToolContext
from okami.core.tools.files import RunShell


def _mk(tmp_path):
    (tmp_path / "sub").mkdir()
    return ToolContext(workspace=tmp_path, chat_id="conv-1")


def test_a_cd_persiste_entre_chamadas(tmp_path):
    ctx = _mk(tmp_path)
    r1 = RunShell().run({"cmd": "cd sub"}, ctx)
    assert r1.ok
    r2 = RunShell().run({"cmd": "pwd"}, ctx)
    assert r2.ok
    assert str(tmp_path / "sub") in r2.output
    r3 = RunShell().run({"cmd": "touch here.txt && ls"}, ctx)
    assert r3.ok and "here.txt" in r3.output
    assert (tmp_path / "sub" / "here.txt").exists()      # rodou DENTRO de sub, não do workspace


def test_b_export_persiste_entre_chamadas(tmp_path):
    # `echo $VAR` cru é bloqueado de propósito (guarda anti-exfil de credencial via env — ver
    # _SENSITIVE_PATH `\becho\s+\$[A-Z_]` em base.py); usamos `test "$FOO" = bar` p/ provar
    # que o valor exportado persistiu sem acionar essa guarda.
    ctx = _mk(tmp_path)
    r1 = RunShell().run({"cmd": "export FOO=bar"}, ctx)
    assert r1.ok
    r2 = RunShell().run({"cmd": 'test "$FOO" = bar && echo matched'}, ctx)
    assert r2.ok and "matched" in r2.output


def test_c_cd_fora_do_jail_e_recusado_e_cwd_intocado(tmp_path):
    ctx = _mk(tmp_path)
    RunShell().run({"cmd": "cd sub"}, ctx)                # entra em sub primeiro
    r = RunShell().run({"cmd": "cd /etc"}, ctx)
    assert r.ok is False
    assert "workspace" in r.output.lower() or "jail" in r.output.lower() or "bloqueado" in r.output.lower()
    r2 = RunShell().run({"cmd": "pwd"}, ctx)
    assert str(tmp_path / "sub") in r2.output              # cwd continua em sub, NÃO foi pra /etc
    assert "/etc" not in r2.output.split("\n")[0]


def test_d_marcador_nao_vaza_no_output(tmp_path):
    ctx = _mk(tmp_path)
    r = RunShell().run({"cmd": "echo oi"}, ctx)
    assert r.ok and "oi" in r.output
    assert "__OKAMI_CWD__" not in r.output
    assert "__OKAMI_ENV_" not in r.output


def test_e_conversas_diferentes_nao_compartilham_cwd(tmp_path):
    ctx1 = ToolContext(workspace=tmp_path, chat_id="conv-a")
    ctx2 = ToolContext(workspace=tmp_path, chat_id="conv-b")
    (tmp_path / "sub").mkdir(exist_ok=True)
    RunShell().run({"cmd": "cd sub"}, ctx1)
    r2 = RunShell().run({"cmd": "pwd"}, ctx2)
    assert str(tmp_path) == r2.output.strip().splitlines()[-1] or \
        r2.output.strip().splitlines()[-1] == str(tmp_path)
    assert "sub" not in r2.output.strip().splitlines()[-1]


def test_session_key_vazia_continua_stateless(tmp_path):
    (tmp_path / "sub").mkdir()
    policy = default_policy()
    reset_session("")
    run_sandboxed("cd sub", tmp_path, policy)             # sem session_key → não passa por run_sandboxed
    res = run_sandboxed("pwd", tmp_path, policy)           # continua no workspace, não em sub
    assert str(tmp_path) in res.output
    assert str(tmp_path / "sub") not in res.output


def test_run_sandboxed_com_session_key_direta(tmp_path):
    policy = default_policy()
    key = "test-direct-key"
    reset_session(key)
    (tmp_path / "sub").mkdir(exist_ok=True)
    run_sandboxed("cd sub", tmp_path, policy, session_key=key)
    res = run_sandboxed("pwd", tmp_path, policy, session_key=key)
    assert str(tmp_path / "sub") in res.output
    reset_session(key)
