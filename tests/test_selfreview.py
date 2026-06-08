"""Incorpora o self-review do próprio Okami (grounded no Hermes): off≠yolo, efeito de shell,
sanitização de env, parser de ação robusto."""

from __future__ import annotations

from okami.core.approval import Approver
from okami.core.harness import parse_action
from okami.core.tools import sanitized_env, shell_has_effect


# ----------------------------------------------------------------- #5 off ≠ yolo
def test_off_is_fail_closed_not_allow_all():
    sens = {"category": "env_file", "risk": "high"}
    assert Approver(mode="off")(sens) is False               # off = sem prompt → NEGA sensível (fail-closed)
    assert Approver(mode="yolo")(sens) is True               # yolo = autoaprova tudo
    assert Approver(mode="manual", prompt=lambda r: "deny")(sens) is False
    assert Approver(mode="manual", prompt=lambda r: "once")(sens) is True
    assert Approver(mode="smart")({"category": "git_push", "risk": "low"}) is True    # auto low-risk
    assert Approver(mode="smart")(sens) is False             # smart não auto-aprova high sem prompt


# ----------------------------------------------------------------- #6 sanitized_env (variações)
def test_sanitized_env_covers_variations(monkeypatch):
    secret = ["OPENAI_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "ANTHROPIC_AUTH_TOKEN",
              "CODEX_REFRESH_TOKEN", "MY_SESSION_ID", "APP_COOKIE", "XAI_OAUTH"]
    keep = ["PATH", "HOME", "LANG", "VIRTUAL_ENV"]
    for k in secret:
        monkeypatch.setenv(k, "leak")
    for k in keep:
        monkeypatch.setenv(k, "/ok")
    env = sanitized_env()
    assert all(k not in env for k in secret)                 # todo segredo removido
    assert all(env.get(k) == "/ok" for k in keep)            # não-sensível mantido


# ----------------------------------------------------------------- #2 efeito de shell
def test_shell_effect_readonly_vs_mutating():
    # find saiu da allowlist de read-only: pra bloquear /-exec rm (P0 do audit 2026-06-07),
    # o classificador trata QUALQUER find como mutante (cai no "desconhecido → efeito" conservador).
    # Custo: 1 falso positivo no watchdog por chamada  (find puro continua sendo read-only NA EXECUÇÃO,
    # só a flag  do ToolResult fica True). Hermes também faz essa classificação conservadora.
    for ro in ("ls -la", "grep -r foo . | cat", "git status", "sed s/a/b/ f"):
        assert shell_has_effect(ro) is False, ro
    for mut in ("rm -rf x", "mkdir y", "git commit -m x", "echo hi > f.txt", "pip install z",
                "sed -i s/a/b/ f", "python build.py",       # python desconhecido → assume efeito
                # P0 do audit 2026-06-07:  e  APAGAM arquivos.
                # O Hermes bloqueia via denylist (tools/approval.py:409-410); o Okami-Agent fechou
                # o buraco no shell_has_effect com regex granular + find na lista de mutantes.
                "find . -name x -delete",
                "find . -name x -print0 -delete",
                "find . -empty -delete",
                "find . -maxdepth 3 -delete",
                "find . -depth -delete",
                "find . -name x -exec rm {} ;",
                "find . -name x -execdir rm {} ;"):
        assert shell_has_effect(mut) is True, mut


def test_sensitive_path_coverage():
    """Audit 2026-06-08: _SENSITIVE_PATH bloqueia segredo REAL (qualificado por path + locais reais), mas
    NÃO arquivos comuns (config.json/settings.json/auth.json soltos eram falso-bloqueio — narrowed)."""
    from okami.core.tools.base import _SENSITIVE_PATH
    should_match = [                                     # toca credencial de verdade
        "cat .docker/config.json", "cat .kube/config", "cat .git-credentials", "cat .config/gh/hosts",
        "cat ~/.bash_history", "cat ~/.zsh_history", "cat ~/.gitconfig",   # NOVOS: histórico/gitconfig
        "ls /run/secrets/", "cat /var/run/secrets/kubernetes.io/serviceaccount/token",  # secret mounts
        "cat .env", "cat id_rsa",
    ]
    for cmd in should_match:
        assert _SENSITIVE_PATH.search(cmd), f"deveria detectar: {cmd}"
    should_not_match = [                                 # arquivo COMUM — não pode bloquear por engano
        "cat config.json", "cat settings.json", "cat .vscode/settings.json", "cat auth.json",
        "cat package.json", "cat tsconfig.json", "cat README.md", "cat ~/.bashrc",
        "ls /tmp", "ls -la", "echo hi", "cat foo.txt", "cat /etc/hostname",
    ]
    for cmd in should_not_match:
        assert not _SENSITIVE_PATH.search(cmd), f"NAO deveria detectar: {cmd}"


def test_hardline_blocks_catastrophes_unconditionally():
    """HARDLINE (Hermes): rm -rf /, mkfs, fork bomb, shutdown… BLOQUEADOS incondicionalmente (nem yolo)."""
    import dataclasses
    import pathlib
    import tempfile

    from okami.core.approval import detect_hardline
    from okami.core.sandbox import default_policy
    from okami.core.tools.base import ToolContext
    from okami.core.tools.files import RunShell
    for cmd in ("rm -rf /", "rm -rf /home", "rm -rf ~", "mkfs.ext4 /dev/sda", "dd if=/dev/zero of=/dev/sda",
                ":(){ :|:& };:", "kill -1 -1", "shutdown -h now", "init 0", "find . | xargs rm -rf /"):
        assert detect_hardline(cmd), f"deveria bloquear: {cmd}"
    for ok in ("rm -rf ./build", "rm -rf node_modules", "rm -rf /tmp/scratch/x",
               "grep 'mkfs\\|kill -1' f", "echo 'rm -rf /' > notes", "git reset --hard"):
        assert detect_hardline(ok) is None, f"NAO deveria bloquear: {ok}"
    # yolo-proof: RunShell em modo yolo ainda RECUSA hardline
    pol = dataclasses.replace(default_policy(), mode="yolo")
    ctx = ToolContext(workspace=pathlib.Path(tempfile.mkdtemp()), sandbox=pol)
    r = RunShell().run({"cmd": "rm -rf /"}, ctx)
    assert not r.ok and "hardline" in r.output           # nem yolo passa


# ----------------------------------------------------------------- #3 parser de ação robusto
def test_parse_action_handles_braces_in_content():
    txt = ('```json\n{"tool":"write_file","args":{"path":"a.json",'
           '"content":"{\\"k\\": {\\"n\\": 1}, \\"arr\\": [1,2]}"}}\n```')
    a = parse_action(txt)
    assert a is not None and a.tool == "write_file" and a.args["path"] == "a.json"
    assert a.args["content"] == '{"k": {"n": 1}, "arr": [1,2]}'   # chaves aninhadas no content preservadas


def test_parse_action_bare_and_last_wins():
    a = parse_action('plano… {"tool":"read_file","args":{"path":"x"}} feito.')   # sem fence
    assert a and a.tool == "read_file"
    last = parse_action('{"tool":"read_file","args":{}}\n{"tool":"respond","args":{"message":"oi"}}')
    assert last and last.tool == "respond"                   # a ÚLTIMA ação vence
