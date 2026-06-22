"""Gerência de PROCESSOS em background (#1/#8/#10 — process manager estilo Hermes).

Roda comando LONGO sem bloquear o turno: `start` devolve um id; `poll`/`wait`/`log`/`kill`/`list`
operam depois — até em OUTRO turno/run, porque o estado vive no disco
(`.okami/processes/<id>.{json,log,exit}`). O comando roda com env SANITIZADO, em sessão própria
(sobrevive ao turno), sob a MESMA política do run_shell (#5: docker/local/perfil), e com bloqueio de
caminho sensível. A saída é redigida (segredo mascarado) antes de voltar pro modelo.

Recursos "confiável pra coisa longa" (#1/#8):
- **reconciliação anti-PID-reuse**: poll compara o start-time do PID (não confia só no kill -0);
- **notify_on_complete**: `drain_completed()` entrega quem terminou (o gateway avisa no chat);
- **watch_patterns**: `watch_hits()` diz quais regex apareceram no log (ex.: "Listening on", "ERROR");
- **paginação de log**: `log_page(offset, limit)` p/ navegar log grande sem despejar tudo;
- **cap de log** (pós-saída) + **TTL/prune** → disco não cresce sem limite;
- **stdin/write interativo + PTY**: `start(interactive=True)` sobe um supervisor (okami/core/ptyproc)
  que segura o mestre do PTY; `write()` injeta input via FIFO (com retry/backoff anti-corrida);
- **sinais**: `signal()` manda TERM/INT/HUP/KILL/USR1… no grupo (ou `docker kill --signal`).
"""

from __future__ import annotations

import errno
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from okami.core.filelock import _proc_start
from okami.core.platform_compat import IS_WINDOWS, popen_session_kwargs, terminate_pid


class ProcessManager:
    _MAX_LOG = 5_000_000           # cap do log armazenado (compactado pós-saída) — disco bounded

    def __init__(self, workspace):
        self.ws = Path(workspace)
        self.dir = self.ws / ".okami" / "processes"

    def _meta(self, pid_id):
        return self.dir / f"{pid_id}.json"

    def _logf(self, pid_id):
        return self.dir / f"{pid_id}.log"

    def _exitf(self, pid_id):
        return self.dir / f"{pid_id}.exit"

    # ----------------------------------------------------------------- start
    def start(self, cmd: str, policy=None, *, notify: bool = False, watch=None,
              interactive: bool = False, chat_id: str = "") -> dict:
        """Sobe `cmd` em background sob a política do run_shell (#5). ValueError se bloqueado.

        `notify` → entra em drain_completed() ao terminar. `watch` → lista de regex monitoradas no log.
        `interactive` → PTY com stdin via FIFO (process_write), só backend local (#1/#8).
        Backend docker (efetivo) → processo ISOLADO; docker EXIGIDO sem Docker → recusa (não cai no local).
        Log/exit são RELATIVOS ao workspace → o wrapper funciona igual dentro do container."""
        import secrets

        from okami.core.tools import _SENSITIVE_PATH, sanitized_env
        if _SENSITIVE_PATH.search(cmd):
            raise ValueError("comando toca caminho sensível (.env/.ssh/credenciais…) — bloqueado")
        eff = policy.effective_backend() if policy is not None else "local"
        if eff == "docker" and not shutil.which("docker"):
            raise ValueError("sandbox: backend=docker exigido, mas Docker ausente — process_start DESABILITADO "
                             "(não caio no local inseguro). Use backend=auto/local, ou instale o Docker.")
        if interactive:
            if eff == "docker":
                raise ValueError("modo interativo (PTY) só no backend local — docker interativo entre turnos "
                                 "não é suportado ainda.")
            return self._start_interactive(cmd, policy, notify=notify, watch=watch, chat_id=chat_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        pid_id = secrets.token_hex(4)
        logrel = shlex.quote(f".okami/processes/{pid_id}.log")    # RELATIVO ao cwd=workspace (vale local E docker)
        exitrel = shlex.quote(f".okami/processes/{pid_id}.exit")
        wrapped = f"({cmd}) > {logrel} 2>&1; echo $? > {exitrel}"  # captura saída + exit code no disco
        container = ""
        if eff == "docker":
            from okami.core.sandbox import docker_argv
            container = f"okami-{pid_id}"
            argv = docker_argv(wrapped, self.ws, policy, name=container)
            proc = subprocess.Popen(argv, cwd=str(self.ws), **popen_session_kwargs())  # POSIX/Windows
        else:
            pre = None
            if policy is not None:
                from okami.core.sandbox import _rlimit_preexec
                pre = _rlimit_preexec(policy)                     # rlimits do perfil (CPU/mem/nproc/fsize)
            proc = subprocess.Popen(["sh", "-c", wrapped], cwd=str(self.ws), env=sanitized_env(),
                                    preexec_fn=pre, **popen_session_kwargs())   # sessão própria → sobrevive ao turno
        meta = {"id": pid_id, "cmd": cmd, "pid": proc.pid, "started": round(time.time(), 3),
                "start_time": _proc_start(proc.pid), "backend": eff, "container": container,
                "notify": bool(notify), "watch": list(watch or []), "notified": False,
                "chat_id": chat_id or ""}    # #2: chat que pediu → notificação vai pro chat CERTO (não _last_chat)
        self._write_meta(pid_id, meta)
        return meta

    def _ctrlf(self, pid_id):
        return self.dir / f"{pid_id}.in"

    def _start_interactive(self, cmd: str, policy=None, *, notify=False, watch=None, chat_id: str = "") -> dict:
        """PTY interativo: supervisor detached segura o mestre + FIFO de input (#1/#8). POSIX-only (PTY/FIFO)."""
        import secrets

        from okami.core.tools import sanitized_env
        if IS_WINDOWS:                                 # PTY/os.mkfifo não existem no Windows → erro claro
            raise ValueError("modo interativo (PTY) não é suportado no Windows — use process_start normal")
        self.dir.mkdir(parents=True, exist_ok=True)
        pid_id = secrets.token_hex(4)
        logp, exitp, ctrlp = self._logf(pid_id), self._exitf(pid_id), self._ctrlf(pid_id)
        if ctrlp.exists():
            ctrlp.unlink()
        os.mkfifo(str(ctrlp))                          # canal de input p/ qualquer turno
        pre = None
        if policy is not None:
            from okami.core.sandbox import _rlimit_preexec
            pre = _rlimit_preexec(policy)
        argv = [sys.executable, "-m", "okami.core.ptyproc", cmd, str(logp), str(exitp), str(ctrlp)]
        try:
            proc = subprocess.Popen(argv, cwd=str(self.ws), env=sanitized_env(),
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, preexec_fn=pre, **popen_session_kwargs())
        except (OSError, ValueError):                  # Popen falhou → não deixa o FIFO órfão acumulando em .okami
            try:
                ctrlp.unlink()
            except OSError:
                pass
            raise
        meta = {"id": pid_id, "cmd": cmd, "pid": proc.pid, "started": round(time.time(), 3),
                "start_time": _proc_start(proc.pid), "backend": "local", "container": "",
                "notify": bool(notify), "watch": list(watch or []), "notified": False,
                "interactive": True, "chat_id": chat_id or ""}
        self._write_meta(pid_id, meta)
        return meta

    def write(self, pid_id: str, data: str, *, submit: bool = True) -> bool:
        """Injeta `data` no stdin de um processo INTERATIVO (via FIFO). `submit` acrescenta \\n (Enter)."""
        meta = self._read_meta(pid_id)
        if not meta or not meta.get("interactive"):
            return False
        ctrlp = self._ctrlf(pid_id)
        if not ctrlp.exists():                         # supervisor já saiu → FIFO removido
            return False
        payload = data + ("\n" if submit and not data.endswith("\n") else "")
        # O_WRONLY|O_NONBLOCK num FIFO dá ENXIO até o supervisor abrir o read end. Sob carga, ProcessStart
        # pode voltar antes disso → RETRY curto com backoff (em vez de falhar na cara do chamador).
        fd = None
        for attempt in range(40):                      # ~2s no total (40 × até 50ms)
            try:
                fd = os.open(str(ctrlp), os.O_WRONLY | os.O_NONBLOCK)
                break
            except OSError as e:
                if e.errno != errno.ENXIO or not ctrlp.exists():
                    return False                       # erro real / FIFO sumiu (processo terminou)
                time.sleep(min(0.05, 0.005 * (attempt + 1)))
        if fd is None:
            return False
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)
        return True

    def _write_meta(self, pid_id, meta) -> None:
        from okami.core.safe_io import write_atomic
        write_atomic(self._meta(pid_id), json.dumps(meta))   # atômico: crash no meio não corrompe a meta do processo

    def _read_meta(self, pid_id):
        p = self._meta(pid_id)
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        except ValueError:
            return None

    # ----------------------------------------------------------------- liveness (anti-reuse)
    def _alive(self, meta: dict) -> bool:
        """Vivo? kill -0 + reconciliação por start-time (PID reciclado por OUTRO processo → morto)."""
        pid = meta.get("pid", 0)
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        stored, cur = meta.get("start_time", ""), _proc_start(pid)
        return not (stored and cur and stored != cur)

    # ----------------------------------------------------------------- poll / log / wait
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
            self._compact_log(pid_id)                  # terminou → compacta se o log ficou gigante
            code = exitf.read_text(encoding="utf-8").strip()
            return {**meta, "status": "exited", "exit_code": int(code) if code.lstrip("-").isdigit() else None}
        if not self._alive(meta):                      # morto sem exitfile (crash/órfão) → reconcilia
            self._compact_log(pid_id)
            return {**meta, "status": "exited", "exit_code": None}
        return {**meta, "status": "running"}

    def _compact_log(self, pid_id: str) -> None:
        """Pós-saída: se o log passou do cap, mantém head+tail (disco bounded). Não toca log vivo."""
        p = self._logf(pid_id)
        try:
            if not p.exists() or p.stat().st_size <= self._MAX_LOG:
                return
        except OSError:
            return
        data = p.read_text(encoding="utf-8", errors="ignore")
        half = self._MAX_LOG // 2
        omitted = len(data) - 2 * half
        p.write_text(f"{data[:half]}\n…[log compactado: {omitted} chars removidos no meio]…\n{data[-half:]}",
                     encoding="utf-8", newline="\n")

    def log(self, pid_id: str, *, tail: int = 4000) -> str:
        p = self._logf(pid_id)
        if not p.exists():
            return ""
        from okami.core.redact import clean_output
        return clean_output(p.read_text(encoding="utf-8", errors="ignore"), head=tail, tail=tail)

    def log_page(self, pid_id: str, *, offset: int = 0, limit: int = 200) -> dict:
        """Paginação por LINHAS (redigidas): {lines, total, offset, shown}. offset<0 conta do fim."""
        p = self._logf(pid_id)
        if not p.exists():
            return {"lines": [], "total": 0, "offset": 0, "shown": 0}
        from okami.core.redact import redact, strip_ansi
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        total = len(lines)
        if offset < 0:
            offset = max(0, total + offset)
        chunk = [redact(strip_ansi(ln)) for ln in lines[offset:offset + max(1, limit)]]
        return {"lines": chunk, "total": total, "offset": offset, "shown": len(chunk)}

    @staticmethod
    def _watch_spec(entry):
        """Normaliza um item de `watch`: 'ERRO' (1 strike) ou {pattern, strikes} → (pattern, strikes)."""
        if isinstance(entry, dict):
            return str(entry.get("pattern", "")), max(1, int(entry.get("strikes", 1) or 1))
        return str(entry), 1

    def watch_hits(self, pid_id: str) -> list[str]:
        """Quais `watch` patterns já bateram o limiar de strikes no log do processo."""
        meta = self._read_meta(pid_id)
        pats = (meta or {}).get("watch") or []
        if not pats:
            return []
        p = self._logf(pid_id)
        text = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
        out = []
        for entry in pats:
            pat, strikes = self._watch_spec(entry)
            if not pat:
                continue
            try:
                if len(re.findall(pat, text)) >= strikes:
                    out.append(pat)
            except re.error:
                pass
        return out

    def drain_watch(self) -> list[dict]:
        """Watch patterns que ACABARAM de bater o limiar — dispara UMA vez por padrão (rate-limit por strike).

        Cada padrão notifica só na 1ª vez que cruza `strikes` (registrado em meta.watch_fired) → sem flood.
        Devolve [{kind:'watch', id, pattern, count, strikes, cmd}]."""
        out: list[dict] = []
        if not self.dir.exists():
            return out
        for f in sorted(self.dir.glob("*.json")):
            meta = self._read_meta(f.stem)
            pats = (meta or {}).get("watch") or []
            if not pats:
                continue
            fired = set((meta or {}).get("watch_fired") or [])
            p = self._logf(f.stem)
            text = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
            changed = False
            for entry in pats:
                pat, strikes = self._watch_spec(entry)
                if not pat or pat in fired:
                    continue
                try:
                    n = len(re.findall(pat, text))
                except re.error:
                    continue
                if n >= strikes:
                    out.append({"kind": "watch", "id": meta["id"], "pattern": pat, "count": n,
                                "strikes": strikes, "cmd": meta.get("cmd", ""),
                                "chat_id": meta.get("chat_id", "")})    # #2: chat de origem
                    fired.add(pat)
                    changed = True
            if changed:
                meta["watch_fired"] = sorted(fired)
                self._write_meta(f.stem, meta)
        return out

    def drain_notifications(self) -> list[dict]:
        """Fila unificada (#P1.4): conclusões (notify_on_complete) + watch hits — cada uma entregue 1x."""
        notes = [{"kind": "complete", **st} for st in self.drain_completed()]
        notes.extend(self.drain_watch())
        return notes

    def wait(self, pid_id: str, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.poll(pid_id)
            if st.get("status") != "running":
                return st
            time.sleep(0.1)
        return self.poll(pid_id)

    # ----------------------------------------------------------------- kill
    def kill(self, pid_id: str) -> bool:
        meta = self._read_meta(pid_id)
        if not meta:
            return False
        ok = False
        if meta.get("backend") == "docker" and meta.get("container"):
            try:
                subprocess.run(["docker", "kill", meta["container"]],   # derruba o container (não só o cliente)
                               capture_output=True, timeout=15)
                ok = True
            except (OSError, subprocess.SubprocessError):
                ok = False
        if terminate_pid(meta["pid"], signal.SIGTERM):  # cross-plataforma: grupo no POSIX, taskkill no Windows
            ok = True                                  # (getpgid/killpg não existem no Windows → terminate_pid trata)
        if ok and not self._exitf(pid_id).exists():
            self._exitf(pid_id).write_text("-15", encoding="utf-8")   # marca terminado por SIGTERM (poll determinístico)
        if self._ctrlf(pid_id).exists():
            try:
                self._ctrlf(pid_id).unlink()                          # remove o FIFO do interativo
            except OSError:
                pass
        return ok

    _SIGNALS = {"TERM": signal.SIGTERM, "INT": signal.SIGINT, "HUP": signal.SIGHUP,
                "KILL": signal.SIGKILL, "QUIT": signal.SIGQUIT, "USR1": signal.SIGUSR1,
                "USR2": signal.SIGUSR2, "CONT": signal.SIGCONT, "STOP": signal.SIGSTOP}

    def signal(self, pid_id: str, name: str = "TERM") -> bool:
        """Manda um sinal arbitrário p/ o grupo do processo (#P1.4 lifecycle): TERM/INT/HUP/KILL/USR1…"""
        meta = self._read_meta(pid_id)
        if not meta:
            return False
        sig = self._SIGNALS.get(name.upper().removeprefix("SIG"))   # removeprefix: lstrip('SIG') comia QUALQUER
        if sig is None:                                              # S/I/G inicial → INT→'NT', STOP→'TOP' (falha muda)
            return False
        if meta.get("backend") == "docker" and meta.get("container"):
            try:
                subprocess.run(["docker", "kill", f"--signal={name.upper().removeprefix('SIG')}", meta["container"]],
                               capture_output=True, timeout=15)
                return True
            except (OSError, subprocess.SubprocessError):
                return False
        return terminate_pid(meta["pid"], sig)         # cross-plataforma (grupo no POSIX, taskkill no Windows)

    def reconcile(self) -> int:
        """Recovery de órfão (#P1.4): processo MORTO sem exitfile (crash/restart do gateway) → grava o
        marcador de saída p/ o estado virar durável (não fica 'running' fantasma). Devolve quantos."""
        fixed = 0
        if not self.dir.exists():
            return 0
        for f in sorted(self.dir.glob("*.json")):
            pid_id = f.stem
            if self._exitf(pid_id).exists():
                continue
            st = self.poll(pid_id)          # poll reapa zumbi + reconcilia (morto sem exit → exited)
            if st.get("status") == "exited" and not self._exitf(pid_id).exists():
                code = st.get("exit_code")
                self._exitf(pid_id).write_text(str(code if code is not None else -1), encoding="utf-8")
                fixed += 1
        return fixed

    # ----------------------------------------------------------------- list / notify / prune
    def list(self) -> list[dict]:
        if not self.dir.exists():
            return []
        return [self.poll(f.stem) for f in sorted(self.dir.glob("*.json"))]

    def drain_completed(self) -> list[dict]:
        """Processos com notify=True que TERMINARAM e ainda não foram avisados — marca como avisados."""
        out = []
        if not self.dir.exists():
            return out
        for f in sorted(self.dir.glob("*.json")):
            meta = self._read_meta(f.stem)
            if not meta or not meta.get("notify") or meta.get("notified"):
                continue
            st = self.poll(f.stem)
            if st.get("status") == "exited":
                meta["notified"] = True
                self._write_meta(f.stem, meta)
                st["chat_id"] = meta.get("chat_id", "")    # #2: roteia a notificação pro chat de origem
                out.append(st)
        return out

    def prune(self, ttl_seconds: float = 86400.0, *, dry_run: bool = False) -> list[str]:
        """Remove (meta+log+exit) processos JÁ TERMINADOS há mais de `ttl_seconds` — cleanup TTL.
        `dry_run` só LISTA o que seria removido (não apaga) — p/ `okami clean --dry-run`."""
        removed, now = [], time.time()
        if not self.dir.exists():
            return removed
        for f in sorted(self.dir.glob("*.json")):
            pid_id = f.stem
            if self.poll(pid_id).get("status") != "exited":
                continue
            exitf = self._exitf(pid_id)
            ts = (exitf.stat().st_mtime if exitf.exists() else f.stat().st_mtime)
            if now - ts > ttl_seconds:
                if not dry_run:
                    for path in (self._meta(pid_id), self._logf(pid_id), self._exitf(pid_id), self._ctrlf(pid_id)):
                        if path.exists():
                            path.unlink()
                removed.append(pid_id)
        return removed
