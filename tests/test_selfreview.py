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
    for ro in ("ls -la", "grep -r foo . | cat", "git status", "sed s/a/b/ f", "find . -name x"):
        assert shell_has_effect(ro) is False, ro
    for mut in ("rm -rf x", "mkdir y", "git commit -m x", "echo hi > f.txt", "pip install z",
                "sed -i s/a/b/ f", "python build.py"):       # python desconhecido → assume efeito
        assert shell_has_effect(mut) is True, mut


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
