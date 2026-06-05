"""Gerência de PROCESSOS em background (#10 — process manager estilo Hermes).

Roda comando LONGO sem bloquear o turno: `start` devolve um id; `poll`/`wait`/`log`/`kill` operam
depois — até em OUTRO turno/run, porque o estado vive no disco (`.okami/processes/<id>.{json,log,exit}`).
O comando roda com env SANITIZADO, em sessão própria (sobrevive ao turno) e com o MESMO bloqueio de
caminho sensível do run_shell. A saída é redigida (segredo mascarado) antes de voltar pro modelo.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import time
from pathlib import Path


class ProcessManager:
    def __init__(self, workspace):
        self.ws = Path(workspace)
        self.dir = self.ws / ".okami" / "processes"

    def _meta(self, pid_id):
        return self.dir / f"{pid_id}.json"

    def _logf(self, pid_id):
        return self.dir / f"{pid_id}.log"

    def _exitf(self, pid_id):
        return self.dir / f"{pid_id}.exit"

    def start(self, cmd: str) -> dict:
        """Sobe `cmd` em background. Levanta ValueError se tocar caminho sensível."""
        import secrets

        from okami.core.tools import _SENSITIVE_PATH, sanitized_env
        if _SENSITIVE_PATH.search(cmd):
            raise ValueError("comando toca caminho sensível (.env/.ssh/credenciais…) — bloqueado")
        self.dir.mkdir(parents=True, exist_ok=True)
        pid_id = secrets.token_hex(4)
        log, exitf = shlex.quote(str(self._logf(pid_id))), shlex.quote(str(self._exitf(pid_id)))
        wrapped = f"({cmd}) > {log} 2>&1; echo $? > {exitf}"     # captura saída + exit code no disco
        proc = subprocess.Popen(["sh", "-c", wrapped], cwd=str(self.ws), env=sanitized_env(),
                                start_new_session=True)          # sessão própria → sobrevive ao turno
        meta = {"id": pid_id, "cmd": cmd, "pid": proc.pid, "started": round(time.time(), 3)}
        self._meta(pid_id).write_text(json.dumps(meta), encoding="utf-8")
        return meta

    def _read_meta(self, pid_id):
        p = self._meta(pid_id)
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        except ValueError:
            return None

    @staticmethod
    def _alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def poll(self, pid_id: str) -> dict:
        meta = self._read_meta(pid_id)
        if not meta:
            return {"id": pid_id, "status": "unknown"}
        try:
            os.waitpid(meta["pid"], os.WNOHANG)        # reap zumbi se for nosso filho (senão kill -0 "vive")
        except (ChildProcessError, OSError):
            pass
        exitf = self._exitf(pid_id)
        if exitf.exists():
            code = exitf.read_text(encoding="utf-8").strip()
            return {**meta, "status": "exited", "exit_code": int(code) if code.lstrip("-").isdigit() else None}
        return {**meta, "status": "running" if self._alive(meta["pid"]) else "exited"}

    def log(self, pid_id: str, *, tail: int = 4000) -> str:
        p = self._logf(pid_id)
        if not p.exists():
            return ""
        from okami.core.redact import clean_output
        return clean_output(p.read_text(encoding="utf-8", errors="ignore"), head=tail, tail=tail)

    def wait(self, pid_id: str, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.poll(pid_id)
            if st.get("status") != "running":
                return st
            time.sleep(0.1)
        return self.poll(pid_id)

    def kill(self, pid_id: str) -> bool:
        meta = self._read_meta(pid_id)
        if not meta:
            return False
        ok = False
        try:
            os.killpg(os.getpgid(meta["pid"]), signal.SIGTERM)   # mata o grupo (start_new_session)
            ok = True
        except OSError:
            try:
                os.kill(meta["pid"], signal.SIGTERM)
                ok = True
            except OSError:
                ok = False
        if ok and not self._exitf(pid_id).exists():
            self._exitf(pid_id).write_text("-15", encoding="utf-8")   # marca terminado por SIGTERM (poll determinístico)
        return ok

    def list(self) -> list[dict]:
        if not self.dir.exists():
            return []
        return [self.poll(f.stem) for f in sorted(self.dir.glob("*.json"))]
