"""Fuzzer 3: tentar bypasses nos regexes sensíveis."""
from __future__ import annotations
import sys
from okami.core.tools.base import _SENSITIVE_PATH

# Tentativas de bypass conhecidas
bypasses = [
    # encoding/quote tricks
    'cat "/home/x/.env"',
    "cat '/home/x/.env'",
    'cat /home/x/./.env',
    'cat /home/x//.env',
    # case mix
    'cat /Home/X/.ENV',
    # redirector trick
    'cat /home/x/.env 2>/dev/null',
    'cat /home/x/.env > /tmp/out',
    # .env variants
    'cat /home/x/.env.local',
    'cat /home/x/.env.bak',
    # symlink-ish: /home/x/.envfile
    'cat /home/x/.envfile',
    # find ainda deveria ser mutante (já validado, mas checar bypass)
    'find . -type f',
    'find / -name x',
    # sed variante
    'sed s/x/y/ file',  # sem -i: read-only
    # chmod com truques
    'chmod u+x file',
    'chmod -R 777 /tmp',
]

print("=== SENSITIVE PATH: tentativas de bypass ===")
fails_sp = 0
for c in bypasses:
    r = bool(_SENSITIVE_PATH.search(c))
    # .env variants DEVEM ser bloqueadas (já tem o regex), outras DEVEM passar
    should = '.env' in c.lower() and '.envfile' not in c
    if should and not r:
        fails_sp += 1
        print(f"  [BYPASS] {c}")
    elif not should and r:
        fails_sp += 1
        print(f"  [FALSO+] {c}")
    else:
        print(f"  [OK ] {c}")

print(f"\nSENSITIVE_PATH: {len(bypasses) - fails_sp}/{len(bypasses)}")
sys.exit(0 if fails_sp == 0 else 1)
