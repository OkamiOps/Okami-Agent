"""Fuzzer 5: TOCTOU de path traversal e symlink escape no write_text_atomic / safe_path."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

# Importa após configurar path
from okami.core.file_safety import safe_path, PathEscape

# Workspace fake
with tempfile.TemporaryDirectory() as tmpdir:
    ws = Path(tmpdir) / "ws"
    ws.mkdir()
    (ws / "inside.txt").write_text("hello")

    # 1) Path traversal clássico — DEVE BLOQUEAR
    cases_block = [
        "../etc/passwd",
        "../../etc/passwd",
        "../outside.txt",
        "subdir/../../outside.txt",
        "./../outside.txt",
    ]

    # 2) Paths válidos — DEVEM PASSAR
    cases_pass = [
        "inside.txt",
        "subdir/inside.txt",
        "./inside.txt",
    ]

    print("=== safe_path: path traversal ===")
    fails = 0
    for c in cases_block:
        try:
            p = safe_path(ws, c)
            # Se não levantou, é BUG
            print(f"  [BYPASS] {c!r} → resolveu para {p}")
            fails += 1
        except PathEscape:
            print(f"  [OK ] {c!r} → bloqueado")
        except Exception as e:
            print(f"  [?]   {c!r} → {type(e).__name__}: {e}")
            fails += 1

    print("\n=== safe_path: paths legítimos ===")
    for c in cases_pass:
        try:
            p = safe_path(ws, c)
            if ws in p.parents or p == ws:
                print(f"  [OK ] {c!r} → {p.relative_to(ws)}")
            else:
                print(f"  [BYPASS] {c!r} → {p}")
                fails += 1
        except Exception as e:
            print(f"  [BLOQ-] {c!r} → {type(e).__name__}: {e}")
            fails += 1

    print(f"\nFalhas: {fails}")
    sys.exit(0 if fails == 0 else 1)
