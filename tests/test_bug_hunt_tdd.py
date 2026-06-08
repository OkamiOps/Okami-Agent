"""Caça-bugs por TDD (audit 2026-06-08): cada teste expressa o comportamento CORRETO; se falha, achou bug.
Comparado com Hermes (tools/approval.py) e OpenClaw quando há dúvida. Mantido como regressão depois do fix.
"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import threading
import time

from okami.core.sandbox import default_policy
from okami.core.tools.base import ToolContext, shell_has_effect
from okami.core.tools.files import ReadFile, RunShell


def test_session_never_runs_two_tasks_concurrently():
    # BUG (race): o dispatch faz check-then-set de s.busy SEM lock, e o finally do _run faz
    # `busy=False` → `if s.queued` (drena) também sem lock. Entre as duas threads (a do canal que chama
    # handle e a do _run que drena), dá pra DOIS _run rodarem na MESMA sessão → corrompe o transcript.
    # Reproduzido deterministicamente: pausa o _run no `if s.queued` e injeta um handle nova nesse instante.
    from okami.core import Task, TaskState
    from okami.channels.terminal import TerminalChannel
    from okami.gateway import AgentEndpoint

    active = {"n": 0, "max": 0}
    obs = threading.Lock()

    def run_task(cfg, ws, goal, **kw):
        with obs:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time.sleep(0.1)
        with obs:
            active["n"] -= 1
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "ok"
        return t

    entered, release = threading.Event(), threading.Event()

    class BarrierList(list):
        _tripped = False

        def __bool__(self):
            if not self._tripped:                       # pausa o finally EXATAMENTE no `if s.queued`
                self._tripped = True
                entered.set()
                release.wait(3)
            return len(self) > 0

    ch = TerminalChannel("okami")                       # console=None → silencioso
    ep = AgentEndpoint("okami", None, tempfile.mkdtemp(), ch, run_task=run_task,
                       spawn=lambda fn: threading.Thread(target=fn, daemon=True).start())
    s = ep.session("c1")
    s.queued = BarrierList([("msg2", None)])
    s.busy = True                                       # simula: tarefa rodando + 1 na fila

    threading.Thread(target=lambda: ep._run("c1", "msg1", s), daemon=True).start()
    assert entered.wait(5), "o _run não chegou no drain"
    threading.Thread(target=lambda: ep.handle("c1", "msg3"), daemon=True).start()
    time.sleep(0.05)                                    # deixa o handle(msg3) decidir (pré-fix: dispara run#3)
    release.set()                                       # libera o finally → drena msg2
    deadline = time.monotonic() + 3                     # espera DRENAR de verdade (sem sleep fixo → robusto sob carga)
    while time.monotonic() < deadline and (s.busy or s.queued or active["n"] > 0):
        time.sleep(0.01)
    assert active["max"] == 1, f"RACE: {active['max']} tarefas concorrentes na MESMA sessão"


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


def test_compact_never_emits_consecutive_same_role():
    # BUG: compact insere a nota como 'user'; se tail[0] também é 'user' (acontece com keep_tail ÍMPAR — e o
    # harness usa keep_tail=3 na recuperação), saem DUAS mensagens 'user' seguidas. OpenAI tolera, mas
    # Anthropic/Claude EXIGE alternância → erro de API na compaction. Não pode haver role repetido em sequência.
    from okami.memory.compaction import compact
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(10):
        msgs.append({"role": "assistant", "content": f"acao {i}"})
        msgs.append({"role": "user", "content": f"[obs] resultado {i}"})
    for kt in (3, 4, 5, 6, 7):
        out, _ = compact(msgs, None, keep_tail=kt)
        roles = [m["role"] for m in out]
        dups = [i for i in range(1, len(roles)) if roles[i] == roles[i - 1]]
        assert not dups, f"keep_tail={kt}: roles consecutivos iguais em {dups}: {roles}"
        # a nota não pode sumir: o conteúdo do resumo tem que aparecer em alguma mensagem
        assert any("auto-compaction" in (m.get("content") or "") for m in out), "a nota de compaction sumiu"


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
