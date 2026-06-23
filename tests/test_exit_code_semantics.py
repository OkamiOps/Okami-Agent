"""Exit-code POR COMANDO (gap vs Hermes _interpret_exit_code). Vários utilitários usam exit≠0 como
SINAL, não erro: grep/rg exit 1 = 'nada casou', diff exit 1 = 'arquivos diferem', test exit 1 =
'condição falsa'. run_shell marcava isso como FALHA (ok=False) → alimentava o circuit-breaker e o
modelo ia 'investigar' um não-erro (parte do 'agente trava e não segue em frente')."""
from __future__ import annotations

from types import SimpleNamespace

from okami.core.tools.files import RunShell, interpret_exit_code


def test_grep_no_match_is_not_failure():
    ok, note = interpret_exit_code("grep foo arquivo.txt", 1)
    assert ok is True and note                                  # exit 1 = nada casou, com nota explicativa


def test_grep_real_error_stays_failure():
    ok, _ = interpret_exit_code("grep foo arquivo.txt", 2)      # exit 2 = erro de verdade (pattern/arquivo)
    assert ok is False


def test_pipeline_uses_last_segment():
    ok, _ = interpret_exit_code("cat arquivo.txt | grep zzz", 1)   # exit do pipeline = do último (grep)
    assert ok is True


def test_diff_differ_is_expected():
    ok, _ = interpret_exit_code("diff a.txt b.txt", 1)
    assert ok is True


def test_env_prefix_and_sudo_are_skipped():
    ok, _ = interpret_exit_code("LC_ALL=C grep foo a.txt", 1)
    assert ok is True


def test_normal_command_failure_stays_failure():
    ok, _ = interpret_exit_code("python script.py", 1)
    assert ok is False


def test_success_is_always_ok():
    ok, note = interpret_exit_code("ls -la", 0)
    assert ok is True and note == ""


def test_run_shell_grep_no_match_returns_ok(tmp_path):
    (tmp_path / "f.txt").write_text("hello world", encoding="utf-8")
    ctx = SimpleNamespace(workspace=tmp_path, sandbox=None, remote=None, cfg=None)
    res = RunShell().run({"cmd": "grep zzzNOPE f.txt"}, ctx)
    assert res.ok is True and "não é erro" in res.output.lower() or "casou" in res.output.lower()
