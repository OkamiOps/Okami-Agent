"""Relatório de uso de disco do Docker + plano de limpeza — stdlib puro (subprocess).

Por padrão só DIAGNOSTICA (roda `docker system df -v`, nunca uma ação destrutiva). Com
`--apply-safe` roda os prunes "seguros" (container/image/network — nunca volume nomeado, nunca
`system prune -a --volumes`; isso continua exigindo confirmação explícita do dono, veja o
SKILL.md).

Uso:
    python3 docker_disk_report.py                # só mostra o relatório (docker system df -v)
    python3 docker_disk_report.py --apply-safe    # roda container/image/network prune (não-volume)
"""

from __future__ import annotations

import argparse
import subprocess
import sys

SAFE_PRUNE_COMMANDS = (
    ["docker", "container", "prune", "-f"],
    ["docker", "image", "prune", "-f"],
    ["docker", "network", "prune", "-f"],
)


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return proc.returncode, (proc.stdout or proc.stderr).strip()
    except FileNotFoundError:
        return 127, "docker não encontrado no PATH"
    except subprocess.TimeoutExpired:
        return 124, "expirou o tempo limite"


def cmd_report() -> int:
    code, out = _run(["docker", "system", "df", "-v"])
    if code != 0:
        print(f"falha ao ler o uso de disco do Docker: {out}", file=sys.stderr)
        return code
    print(out)
    return 0


def cmd_apply_safe() -> int:
    print("--- antes ---")
    _, before = _run(["docker", "system", "df"])
    print(before)

    for cmd in SAFE_PRUNE_COMMANDS:
        print(f"$ {' '.join(cmd)}")
        code, out = _run(cmd)
        print(out)
        if code != 0:
            print(f"aviso: {' '.join(cmd)} saiu com código {code}", file=sys.stderr)

    print("--- depois ---")
    _, after = _run(["docker", "system", "df"])
    print(after)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply-safe", action="store_true",
                    help="além do relatório, roda prune de container/image/network (nunca volume)")
    return p


def main() -> int:
    a = build_parser().parse_args()
    if a.apply_safe:
        return cmd_apply_safe()
    return cmd_report()


if __name__ == "__main__":
    raise SystemExit(main())
