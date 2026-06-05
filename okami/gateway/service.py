"""Gateway como SERVIÇO gerenciado (#multi-profile) — launchd (macOS) / systemd user (Linux).

O `okami gateway` (background) é só um subprocess destacado: morre no reboot/logout. Aqui a gente
instala o gateway como serviço de verdade — sobe no boot, reinicia se cair, e tem start/stop/status.
Roda `okami gateway --foreground` no diretório do projeto, com OKAMI_HOME no ambiente. Os renderizadores
são puros (testáveis); install/uninstall chamam launchctl/systemctl de forma defensiva.
"""

from __future__ import annotations

import shutil
import subprocess  # launchctl/systemctl — sempre LISTA de args, nunca shell=True
import sys
from pathlib import Path

LABEL = "ops.okami.gateway"          # launchd label / base do nome systemd


def detect_platform() -> str:
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform.startswith("linux"):
        return "systemd"
    return "unsupported"


def exec_argv() -> list[str]:
    """Comando que o serviço roda: o launcher `okami` se existir no PATH, senão `python -m okami.cli`."""
    okami = shutil.which("okami")
    base = [okami] if okami else [sys.executable, "-m", "okami.cli"]
    return [*base, "gateway", "--foreground"]


def launchd_plist_path(label: str = LABEL) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def systemd_unit_path(name: str = "okami-gateway") -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{name}.service"


def log_path() -> Path:
    from okami.home import okami_home
    return okami_home() / "logs" / "gateway.log"


def render_launchd(argv: list[str], workdir: str, log: str, okami_home: str, label: str = LABEL) -> str:
    args = "\n".join(f"      <string>{a}</string>" for a in argv)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f'  <key>Label</key><string>{label}</string>\n'
        f'  <key>ProgramArguments</key>\n  <array>\n{args}\n  </array>\n'
        f'  <key>WorkingDirectory</key><string>{workdir}</string>\n'
        f'  <key>EnvironmentVariables</key>\n  <dict><key>OKAMI_HOME</key><string>{okami_home}</string></dict>\n'
        '  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><true/>\n'
        f'  <key>StandardOutPath</key><string>{log}</string>\n'
        f'  <key>StandardErrorPath</key><string>{log}</string>\n'
        '</dict>\n</plist>\n'
    )


def _systemd_argv(argv: list[str]) -> str:
    """ExecStart systemd-safe: arg com espaço/aspas vai entre aspas, ESCAPANDO `\\` e `"` internos
    (estilo systemd) — path com espaço OU caractere especial não quebra a unit."""
    out = []
    for a in argv:
        if " " in a or '"' in a or "'" in a or "\\" in a:
            out.append('"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"')
        else:
            out.append(a)
    return " ".join(out)


def render_systemd(argv: list[str], workdir: str, log: str, okami_home: str) -> str:
    return (
        "[Unit]\n"
        "Description=Okami Agent gateway (Telegram/canais)\n"
        "After=network-online.target\nWants=network-online.target\n\n"
        "[Service]\nType=simple\n"
        f"WorkingDirectory={workdir}\n"
        f"Environment=OKAMI_HOME={okami_home}\n"
        f"ExecStart={_systemd_argv(argv)}\n"
        "Restart=on-failure\nRestartSec=5\n"
        f"StandardOutput=append:{log}\nStandardError=append:{log}\n\n"
        "[Install]\nWantedBy=default.target\n"
    )


def _run(argv: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=30)   # argv fixo, sem shell
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def install(workdir: str | None = None, *, emit=print) -> bool:
    """Gera o unit e carrega o serviço (idempotente). Devolve True se instalou."""
    plat = detect_platform()
    if plat == "unsupported":
        emit(f"✗ serviço não suportado em {sys.platform} (use `okami gateway` em background).")
        return False
    from okami.home import okami_home
    wd = str(Path(workdir or Path.cwd()).resolve())
    home = str(okami_home())
    log = log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = exec_argv()
    if plat == "launchd":
        p = launchd_plist_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_launchd(argv, wd, str(log), home), encoding="utf-8")
        _run(["launchctl", "unload", str(p)])                 # idempotente (ignora se não estava)
        rc, out = _run(["launchctl", "load", str(p)])
        emit(f"✓ serviço instalado: {p}" if rc == 0 else f"✗ launchctl load falhou: {out}")
        return rc == 0
    p = systemd_unit_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_systemd(argv, wd, str(log), home), encoding="utf-8")
    _run(["systemctl", "--user", "daemon-reload"])
    rc, out = _run(["systemctl", "--user", "enable", "--now", p.name])
    emit(f"✓ serviço instalado: {p}" if rc == 0 else f"✗ systemctl enable falhou: {out}")
    return rc == 0


def uninstall(*, emit=print) -> bool:
    plat = detect_platform()
    if plat == "launchd":
        p = launchd_plist_path()
        _run(["launchctl", "unload", str(p)])
        p.unlink(missing_ok=True)
        emit("✓ serviço removido.")
        return True
    if plat == "systemd":
        p = systemd_unit_path()
        _run(["systemctl", "--user", "disable", "--now", p.name])
        p.unlink(missing_ok=True)
        _run(["systemctl", "--user", "daemon-reload"])
        emit("✓ serviço removido.")
        return True
    emit("nada a remover.")
    return False


def control(action: str, *, emit=print) -> bool:
    """start | stop | restart | status — delega ao gerenciador do SO."""
    plat = detect_platform()
    if plat == "launchd":
        p = launchd_plist_path()
        if action == "status":
            rc, out = _run(["launchctl", "list"])
            on = LABEL in out
            emit(f"● serviço no ar ({LABEL})" if on else "○ serviço parado/não instalado")
            return on
        verb = {"start": "load", "stop": "unload", "restart": "kickstart"}.get(action)
        if action == "restart":
            rc, out = _run(["launchctl", "kickstart", "-k", f"gui/{_uid()}/{LABEL}"])
        else:
            rc, out = _run(["launchctl", verb, str(p)])
        emit(f"✓ {action}" if rc == 0 else f"✗ {action}: {out}")
        return rc == 0
    if plat == "systemd":
        name = systemd_unit_path().name
        if action == "status":
            rc, out = _run(["systemctl", "--user", "is-active", name])
            emit(out or ("ativo" if rc == 0 else "parado"))
            return rc == 0
        rc, out = _run(["systemctl", "--user", action, name])
        emit(f"✓ {action}" if rc == 0 else f"✗ {action}: {out}")
        return rc == 0
    emit(f"✗ serviço não suportado em {sys.platform}.")
    return False


def _uid() -> int:
    import os
    return os.getuid() if hasattr(os, "getuid") else 0
