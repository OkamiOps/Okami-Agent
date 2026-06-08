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


def test_read_file_errors_are_actionable_not_raw_oserror():
    # BUG (thrash): read_file num DIRETÓRIO devolvia '[Errno 21] Is a directory: /private/var/...' (cru,
    # com path de temp) e o agente RE-TENTAVA dezenas de vezes. read_file de inexistente não guiava. Erros
    # têm que ser ACIONÁVEIS (→ list_dir / find_files) p/ o modelo parar de chutar caminho.
    from okami.core.tools.base import ToolContext
    from okami.core.tools.files import ReadFile
    ws = pathlib.Path(tempfile.mkdtemp())
    (ws / "subdir").mkdir()
    ctx = ToolContext(workspace=ws)
    rdir = ReadFile().run({"path": "subdir"}, ctx)
    assert rdir.ok is False
    assert "diret" in rdir.output.lower() and "list_dir" in rdir.output, f"erro de diretório não guia: {rdir.output!r}"
    assert "Errno" not in rdir.output and "/private/var" not in rdir.output, "vazou OSError cru/path de temp"
    rmiss = ReadFile().run({"path": "okami/cli/nope.py"}, ctx)
    assert rmiss.ok is False
    assert "find_files" in rmiss.output or "list_dir" in rmiss.output, f"not-found não guia: {rmiss.output!r}"


def test_tools_dont_crash_on_malformed_args():
    # BUG (robustez): args None/tipo-errado (o modelo fraco emite {"cmd": null}) faziam a tool LEVANTAR
    # (TypeError/AttributeError) em vez de devolver ToolResult(False, msg clara). O harness contém, mas a
    # msg vira traceback feio e a falha repetida bate o circuit-breaker. Tool tem que validar e dar erro limpo.
    from okami.core.sandbox import default_policy
    from okami.core.tools.base import ToolContext
    from okami.core.tools.files import EditFile, FindFiles, ListDir, ReadFile, RunShell, WriteFile
    ws = pathlib.Path(tempfile.mkdtemp())
    ctx = ToolContext(workspace=ws, sandbox=default_policy())
    cases = [
        (RunShell(), {"cmd": None}), (RunShell(), {"cmd": 123}), (RunShell(), {"cmd": ["echo", "x"]}),
        (ReadFile(), {"path": None}), (ReadFile(), {"path": 123}),
        (WriteFile(), {"path": None, "content": "x"}), (WriteFile(), {"path": "f.txt", "content": None}),
        (WriteFile(), {"path": "f2.txt", "content": b"\x00\x01"}),
        (EditFile(), {"path": "f.txt", "old": None, "new": "x"}),
        (ListDir(), {"path": 123}), (FindFiles(), {"query": None}), (FindFiles(), {"query": 123}),
    ]
    from okami.core.tools.base import ToolResult
    for tool, args in cases:
        try:
            r = tool.run(args, ctx)
        except Exception as e:  # noqa: BLE001
            raise AssertionError(f"{tool.name} levantou {type(e).__name__} com args={args!r}: {e}") from e
        assert isinstance(r, ToolResult), f"{tool.name}({args}) não devolveu ToolResult"


def test_memory_bars_natural_language_credentials():
    # BUG: looks_secret só casa token ESTRUTURADO (sk-/ghp_/AKIA/Bearer). Uma senha em LINGUAGEM NATURAL
    # ("minha senha é X") passava → virava memória durável (persistida + recall → re-injetada no provider).
    # O barramento de memória tem que recusar disclosure de credencial (over-bar é barato aqui).
    from okami.memory.policy import prepare
    for s in ("minha senha do banco é hunter2correcthorse",
              "password is supersecret123",
              "a senha do servidor: trocaisso999",
              "meu PIN é 837465",
              "the db credential = p0stgr3sR00t"):
        assert prepare(s, source="test:user") is None, f"credencial NL virou memória: {s!r}"
    # fatos normais (sem disclosure de credencial) AINDA viram memória
    for s in ("o usuário prefere respostas curtas",
              "decidimos usar Postgres no projeto",
              "esqueci a senha do wifi de novo"):      # menciona 'senha' mas NÃO revela valor → ok
        assert prepare(s, source="test:user") is not None, f"fato normal foi barrado por engano: {s!r}"


def test_run_shell_output_redacts_secrets():
    # BUG (defense-in-depth): a saída do run_shell síncrono ia VERBATIM p/ o contexto do LLM + transcript.
    # Um token impresso por um comando (gh auth, build log, etc.) vazava. O log de processo em background e
    # o event-log JÁ redigem — o run_shell síncrono não (inconsistente). redact() tem que valer aqui também.
    from okami.core.sandbox import default_policy
    from okami.core.tools.base import ToolContext
    from okami.core.tools.files import RunShell
    ws = pathlib.Path(tempfile.mkdtemp())
    ctx = ToolContext(workspace=ws, sandbox=default_policy())
    sk = "sk-" + "abcdef0123456789ABCDEF"            # tokens MONTADOS (sem literal contíguo → não aciona o
    gh = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUV012345"      # secret-scan do repo), mas redact() casa em runtime
    r = RunShell().run({"cmd": f"echo 'k={sk} Bearer {gh}'"}, ctx)
    assert r.ok
    assert sk not in r.output, "token sk- vazou na saída do run_shell"
    assert gh not in r.output, "token GitHub vazou"
    assert "exit=0" in r.output                      # estrutura preservada (só o segredo é mascarado)


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
