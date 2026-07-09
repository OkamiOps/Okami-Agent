"""Checa se o Docker está instalado e o daemon está de pé — stdlib puro (subprocess).

Existe pra mitigar uma falha real de uso: um agente que roda `docker ...` numa VPS onde o daemon
não está no ar fica com o shell pendurado (o comando trava esperando o socket) em vez de falhar
rápido e claro. Rode isto ANTES de qualquer sequência de comandos `docker`/`docker compose` — o
resultado te diz se dá pra prosseguir ou se precisa primeiro subir o daemon.

Uso:
    python3 docker_daemon_check.py
Saída: JSON de uma linha com {"cli": bool, "daemon_up": bool, "compose_v2": bool, "hint": str|null}.
Exit code: 0 se o daemon está de pé e pronto pra uso; 1 caso contrário (leia "hint").
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess


def _run(cmd: list[str], timeout: float = 5.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or proc.stderr).strip()
    except FileNotFoundError:
        return 127, "comando não encontrado"
    except subprocess.TimeoutExpired:
        return 124, "expirou o tempo limite"


def _hint_for_down_daemon() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "abra o Docker Desktop (ou 'colima start' se usar Colima) e rode de novo"
    if system == "linux":
        return "provável VPS/systemd: rode 'sudo systemctl start docker' e confirme com 'sudo systemctl status docker'"
    return "inicie o serviço/aplicativo do Docker para este sistema e rode de novo"


def main() -> int:
    result = {"cli": False, "daemon_up": False, "compose_v2": False, "hint": None}

    if shutil.which("docker") is None:
        result["hint"] = "docker não está instalado ou não está no PATH"
        print(json.dumps(result))
        return 1
    result["cli"] = True

    code, out = _run(["docker", "info", "--format", "{{.ServerVersion}}"])
    if code != 0:
        result["hint"] = f"{_hint_for_down_daemon()} (docker info falhou: {out[:200]})"
        print(json.dumps(result))
        return 1
    result["daemon_up"] = True

    code, _ = _run(["docker", "compose", "version"])
    result["compose_v2"] = code == 0

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
