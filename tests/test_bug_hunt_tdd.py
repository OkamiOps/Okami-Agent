"""Caça-bugs por TDD (audit 2026-06-08): cada teste expressa o comportamento CORRETO; se falha, achou bug.
Comparado com Hermes (tools/approval.py) e OpenClaw quando há dúvida. Mantido como regressão depois do fix.
"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile

from okami.core.sandbox import default_policy
from okami.core.tools.base import ToolContext, shell_has_effect
from okami.core.tools.files import ReadFile, RunShell


def _ws_with_secrets():
    # conteúdo INÓCUO de propósito: o bloqueio é pelo NOME/path (.env, id_rsa) — não pelo conteúdo. Evita
    # acionar o secret-scan do repo com segredo-fixture realista.
    ws = pathlib.Path(tempfile.mkdtemp())
    (ws / ".env").write_text("EXEMPLO_VAR=valor-de-teste-nao-secreto\n", encoding="utf-8")
    (ws / "id_rsa").write_text("conteudo-fake-de-chave-so-pra-teste\n", encoding="utf-8")
    (ws / "normal.txt").write_text("texto comum\n", encoding="utf-8")
    return ws


def test_read_file_blocks_secrets_like_shell_does():
    # BUG (assimetria): run_shell `cat .env` é BLOQUEADO, mas read_file `.env` vazava o segredo. A injeção
    # de prompt só trocava a tool. read_file tem que ter o MESMO _SENSITIVE_PATH do shell (yolo libera).
    ws = _ws_with_secrets()
    ctx = ToolContext(workspace=ws, sandbox=default_policy())
    assert RunShell().run({"cmd": "cat .env"}, ctx).ok is False           # shell já bloqueia (baseline)
    assert ReadFile().run({"path": ".env"}, ctx).ok is False              # read_file TEM que bloquear igual
    assert ReadFile().run({"path": "id_rsa"}, ctx).ok is False
    assert ReadFile().run({"path": "normal.txt"}, ctx).ok is True         # arquivo comum: lê normal
    # yolo = intenção explícita → libera (mesma válvula do shell)
    yolo = ToolContext(workspace=ws, sandbox=dataclasses.replace(default_policy(), mode="yolo"))
    assert ReadFile().run({"path": ".env"}, yolo).ok is True


def test_archive_skill_refuses_path_traversal():
    # BUG (path traversal): manage_skill(action=archive) roda ANTES da validação de nome, e _archive_skill
    # fazia `src = root/name` + shutil.move SEM validar → `name='../victim'` movia/destruía um diretório
    # IRMÃO do skills_dir (fora do jail). Tem que recusar qualquer name que não seja filho DIRETO de root.
    from okami.learning.curator import _archive_skill
    base = pathlib.Path(tempfile.mkdtemp())
    root = base / "skills"
    root.mkdir()
    (root / "realskill").mkdir()
    (root / "realskill" / "SKILL.md").write_text("x", encoding="utf-8")
    victim = base / "victim"                       # IRMÃO do skills_dir → alcançável por ../victim
    victim.mkdir()
    (victim / "important.txt").write_text("não me mova", encoding="utf-8")
    for evil in ("../victim", "../../" + victim.name, "..", "/etc"):
        assert _archive_skill(root, evil) is False, f"traversal deveria ser recusado: {evil!r}"
    assert victim.exists() and (victim / "important.txt").exists(), "o diretório-vítima foi movido/destruído!"
    assert _archive_skill(root, "realskill") is True   # skill legítima (filho direto) ainda arquiva
    assert not (root / "realskill").exists() and (root / ".archive" / "realskill").exists()


def test_env_wrapper_does_not_hide_mutating_command():
    # BUG: `env` está na allowlist read-only, mas `env VAR=val CMD` EXECUTA CMD. Um comando que muta
    # (script, node, python) wrapado em env era classificado read-only → escapava do watchdog/batch.
    # `env` sozinho (imprime ambiente) segue read-only.
    assert shell_has_effect("env FOO=1 ./deploy.sh") is True
    assert shell_has_effect("env X=1 node server.js") is True
    assert shell_has_effect("env A=b python write.py") is True
    assert shell_has_effect("env -i bash setup.sh") is True
    # bare env / printenv continuam read-only (não executam nada)
    assert shell_has_effect("env") is False
    assert shell_has_effect("printenv") is False
    assert shell_has_effect("env | grep PATH") is False
