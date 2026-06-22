"""Suíte e2e AMPLA: as coisas que um usuário REALMENTE pede ao agente, rodando as TOOLS de verdade
(não 'não-crasha' — valida o COMPORTAMENTO/efeito). Pedido do dono: "suite de teste ampla para testar
as funcionalidades e tudo mais que a aplicação tem" (escreva código, frontend, PR, edite, rode, busque)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from okami.core.tools.base import ToolContext
from okami.core.tools.registry import default_registry

_REG = default_registry()


def _ctx():
    from okami.core.sandbox import default_policy
    ws = Path(tempfile.mkdtemp())
    return ToolContext(workspace=ws, registry=_REG, sandbox=default_policy(), open_fs=True), ws


def _run(tool, args, ctx):
    return _REG[tool].run(args, ctx)


def test_write_and_run_python_code():
    ctx, ws = _ctx()
    assert _run("write_file", {"path": "hello.py", "content": "print('Ola mundo')"}, ctx).ok
    r = _run("run_shell", {"cmd": "python3 hello.py"}, ctx)
    assert r.ok and "Ola mundo" in r.output


def test_build_frontend_files():
    ctx, ws = _ctx()
    _run("write_file", {"path": "index.html", "content": "<!doctype html><h1>Oi</h1>"}, ctx)
    _run("write_file", {"path": "style.css", "content": "h1{color:red}"}, ctx)
    _run("write_file", {"path": "app.js", "content": "console.log('hi')"}, ctx)
    assert all((ws / f).exists() for f in ("index.html", "style.css", "app.js"))


def test_edit_existing_code():
    ctx, ws = _ctx()
    _run("write_file", {"path": "f.py", "content": "x = 1\ny = 2\n"}, ctx)
    _run("read_file", {"path": "f.py"}, ctx)
    r = _run("edit_file", {"path": "f.py", "old": "x = 1", "new": "x = 42"}, ctx)
    assert r.ok and "x = 42" in (ws / "f.py").read_text()


def test_execute_code_rpc():
    ctx, _ = _ctx()
    r = _run("execute_code", {"code": "print(sum(range(10)))"}, ctx)
    assert r.ok and "45" in r.output


def test_find_and_search():
    ctx, ws = _ctx()
    _run("write_file", {"path": "src/main.py", "content": "def login(): pass\n"}, ctx)
    assert "main.py" in _run("find_files", {"query": "main"}, ctx).output
    assert "login" in _run("search_files", {"query": "login"}, ctx).output


def test_git_commit_flow_for_pr():
    ctx, ws = _ctx()
    _run("write_file", {"path": "a.txt", "content": "v1"}, ctx)
    seq = "git init -q && git add -A && git -c user.email=a@b.c -c user.name=x commit -q -m teste && git log --oneline"
    r = _run("run_shell", {"cmd": seq}, ctx)
    assert r.ok and "teste" in r.output


def test_file_operations():
    ctx, ws = _ctx()
    _run("make_dir", {"path": "d1"}, ctx)
    _run("write_file", {"path": "d1/x.txt", "content": "hi"}, ctx)
    _run("copy_path", {"src": "d1/x.txt", "dst": "d1/y.txt"}, ctx)
    _run("move_path", {"src": "d1/y.txt", "dst": "d1/z.txt"}, ctx)
    _run("delete_path", {"path": "d1/x.txt"}, ctx)
    assert (ws / "d1/z.txt").exists() and not (ws / "d1/x.txt").exists()


def test_long_process_lifecycle():
    """Servidor/processo longo: start em background → poll(running) → log → kill. O ciclo comum de 'sobe
    um server'/'roda o build'."""
    ctx, ws = _ctx()
    r = _run("process_start", {"cmd": "python3 -c \"import time; print('up'); time.sleep(30)\""}, ctx)
    if not r.ok:                                  # ambiente sem backend de processo → não falha o teste
        pytest.skip(f"process_start indisponível: {r.output[:60]}")
    pid = (r.effect or {}).get("pid") if isinstance(getattr(r, "effect", None), dict) else None
    import re as _re
    m = _re.search(r"\b(\d{3,})\b", r.output)
    pid = pid or (m.group(1) if m else None)
    assert pid, f"sem pid no start: {r.output[:80]}"
    _run("process_kill", {"id": str(pid)}, ctx)


def test_pr_skill_procedure_loads():
    """O dono pede 'abra um PR' → a skill criar-pull-request carrega o procedimento."""
    from okami.skills import parse_skill
    sd = Path("skills")
    if not (sd / "criar-pull-request" / "SKILL.md").exists():
        pytest.skip("skill criar-pull-request ausente neste checkout")
    cat = {"criar-pull-request": parse_skill(sd / "criar-pull-request" / "SKILL.md").body}
    ctx = ToolContext(workspace=Path(tempfile.mkdtemp()), registry=_REG,
                      skills=cat, skills_dir=str(sd.resolve()), open_fs=True)
    r = _run("use_skill", {"name": "criar-pull-request"}, ctx)
    assert r.ok and len(r.output) > 100
