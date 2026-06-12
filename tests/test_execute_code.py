"""execute_code — programmatic tool calling (pesquisa #5 item 30, a MAIOR economia de tokens).

Um script Python roda em SUBPROCESSO (env sanitizado, cwd=workspace, timeout) e chama tools
READ-ONLY via RPC `tool(name, **args)`; os resultados intermediários ficam NO SCRIPT — só o
stdout final volta pro contexto. N idas-e-voltas de leitura viram 1 turno.

Segurança: allowlist read-only no RPC (sem bypass de aprovação), perfil read-only bloqueia a
tool inteira, código com padrão perigoso (subprocess/socket/rmtree…) é SENSÍVEL (go/no-go),
caminho sensível no código é bloqueado, superfície remota não tem a tool.
"""
from __future__ import annotations

from okami.core.tools import ToolContext, default_registry
from okami.core.tools.execute_code import ExecuteCode


def _ctx(tmp_path, **kw):
    return ToolContext(workspace=tmp_path, registry=default_registry(), **kw)


def test_plain_python_returns_stdout(tmp_path):
    res = ExecuteCode().run({"code": "print(2 + 2)"}, _ctx(tmp_path))
    assert res.ok, res.output
    assert "4" in res.output


def test_rpc_reads_file_but_content_stays_in_script(tmp_path):
    (tmp_path / "dados.txt").write_text("linha\n" * 500, encoding="utf-8")
    code = (
        "texto = tool('read_file', path='dados.txt')\n"
        "print('linhas:', len(texto.splitlines()))\n"
    )
    res = ExecuteCode().run({"code": code}, _ctx(tmp_path))
    assert res.ok, res.output
    assert "linhas: 500" in res.output
    assert res.output.count("linha") < 5            # o CONTEÚDO bruto não voltou pro contexto


def test_rpc_aggregates_many_reads_in_one_turn(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("x" * (i + 1), encoding="utf-8")
    code = (
        "total = 0\n"
        "for i in range(5):\n"
        "    total += len(tool('read_file', path=f'f{i}.txt'))\n"
        "print('total:', total)\n"
    )
    res = ExecuteCode().run({"code": code}, _ctx(tmp_path))
    assert res.ok and "total: 15" in res.output     # 5 leituras → 1 turno


def test_rpc_denies_non_readonly_tool(tmp_path):
    code = (
        "try:\n"
        "    tool('run_shell', cmd='ls')\n"
        "except Exception as e:\n"
        "    print('negada:', e)\n"
    )
    res = ExecuteCode().run({"code": code}, _ctx(tmp_path))
    assert res.ok
    assert "negada:" in res.output and "run_shell" in res.output


def test_script_error_reports_traceback(tmp_path):
    res = ExecuteCode().run({"code": "1/0"}, _ctx(tmp_path))
    assert not res.ok
    assert "ZeroDivisionError" in res.output


def test_timeout_kills_script(tmp_path):
    res = ExecuteCode().run({"code": "import time; time.sleep(30)", "timeout": 1}, _ctx(tmp_path))
    assert not res.ok
    assert "timeout" in res.output.lower() or "cortado" in res.output


def test_readonly_profile_blocks_tool(tmp_path):
    class Box:
        mode = "read-only"
    res = ExecuteCode().run({"code": "print(1)"}, _ctx(tmp_path, sandbox=Box()))
    assert not res.ok and "read-only" in res.output


def test_sensitive_path_in_code_blocked(tmp_path):
    res = ExecuteCode().run({"code": "print(open('/home/x/.ssh/id_rsa').read())"}, _ctx(tmp_path))
    assert not res.ok and "sensível" in res.output


# ------------------------------------------------------------------ aprovação / policy
def test_dangerous_code_is_sensitive():
    from okami.core.approval import classify
    s = classify("execute_code", {"code": "import subprocess; subprocess.run(['x'])"})
    assert s is not None and s.risk == "high"
    assert classify("execute_code", {"code": "print(tool('read_file', path='a'))"}) is None


def test_registered_and_denied_on_remote():
    from okami.core.tool_policy import denied
    assert "execute_code" in default_registry()
    assert denied("telegram", "execute_code")
    assert not denied("cli", "execute_code")
