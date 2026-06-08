"""Fuzzer de regressão: _SENSITIVE_PATH, _SHELL_MUTATES, _FILE_RULES (approval), classify().

Reproduz os achados do audit 2026-06-08 (commit 64ce387) — execute:
    uv run python scripts/audit_fuzz_approval_and_shell.py

Saída: cada caso como BLOQUEADO (passa) / BYPASS (falha) / FALSO+ (bloqueio desnecessário).
Exit code != 0 se houver qualquer falha — útil em CI.
"""

from __future__ import annotations

import sys
from okami.core.tools.base import _SENSITIVE_PATH, _SHELL_MUTATES, shell_has_effect
from okami.core.approval import classify

# Casos que DEVEM ser detectados como sensíveis (esperado: blocked=True)
SENSITIVE_MUST_BLOCK = [
    "cat /var/run/secrets/kubernetes.io/serviceaccount/token",
    "cat /proc/self/environ",
    "cat /proc/1/environ",
    "cat /home/x/.bash_history",
    "cat /home/x/.python_history",
    "cat /home/x/.zsh_history",
    "cat /home/x/.gitconfig",
    "ls /run/secrets/",
    "printenv",
    "env | grep -i key",
    "sed -i s/x/y/ /private/etc/sudoers",
]

# Casos que NÃO devem ser detectados (esperado: blocked=False) — pra pegar FALSO+
SENSITIVE_MUST_PASS = [
    "ls -la /tmp",
    "cat src/main.py",
    "pwd",
    "echo hello world",
]

# Casos que DEVEM ser classificados como mutantes (esperado: mutates=True)
SHELL_MUST_MUTATE = [
    "rm -rf /tmp/x",
    "rmdir /tmp/dir",
    "mv a b",
    "cp a b",
    "sed -i s/x/y/ file",
    "git commit -m x",
    "git push origin main",
    "find /tmp -name x -delete",
    "find /tmp -name x -exec rm {} +",
    "find /tmp -empty -delete",
    "npm install lodash",
    "pip install requests",
    "docker rmi nginx",
    "kill 1234",
]

# Casos que NÃO devem ser classificados como mutantes (read-only) — pra pegar FALSO+
SHELL_MUST_PASS = [
    "ls -la /tmp",
    "cat src/main.py",
    "git status",
    "git log --oneline -5",
    "git diff",
    "git show HEAD",
    "git branch",
    "pwd",
    "grep -r foo src/",
]


def run() -> int:
    failures = 0
    total = 0

    print("=== _SENSITIVE_PATH (BLOQUEIO esperado em MUST_BLOCK) ===")
    for c in SENSITIVE_MUST_BLOCK:
        total += 1
        ok = bool(_SENSITIVE_PATH.search(c))
        status = "OK " if ok else "BYPASS"
        if not ok:
            failures += 1
        print(f"  [{status}] {c}")

    print("\n=== _SENSITIVE_PATH (PASSA esperado em MUST_PASS) ===")
    for c in SENSITIVE_MUST_PASS:
        total += 1
        ok = not _SENSITIVE_PATH.search(c)
        status = "OK " if ok else "FALSO+"
        if not ok:
            failures += 1
        print(f"  [{status}] {c}")

    print("\n=== _SHELL_MUTATES (MUTA esperado em MUST_MUTATE) ===")
    for c in SHELL_MUST_MUTATE:
        total += 1
        ok = shell_has_effect(c)
        status = "OK " if ok else "BYPASS"
        if not ok:
            failures += 1
        print(f"  [{status}] {c}")

    print("\n=== _SHELL_MUTATES (PASSA esperado em MUST_PASS) ===")
    for c in SHELL_MUST_PASS:
        total += 1
        ok = not shell_has_effect(c)
        status = "OK " if ok else "FALSO+"
        if not ok:
            failures += 1
        print(f"  [{status}] {c}")

    print(f"\n=== RESUMO: {total - failures}/{total} passaram ({failures} falhas) ===")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
