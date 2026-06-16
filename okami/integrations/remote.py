"""Ambiente remoto — o agente "entra" num host (nó Tailscale ou user@host) e seus comandos rodam LÁ.

`RemoteTarget` monta o comando ssh/tailscale e executa via um runner injetável (subprocess por padrão,
mockável no teste). Tailscale SSH é o caminho primário (usa a ACL do Tailscale, sem gerir chave); ssh
é o fallback, com ControlMaster pra reusar a conexão entre chamadas (rápido) — espelha o
SSHEnvironment do Hermes. Nada aqui lê chave ou injeta segredo: delega ao `tailscale`/`ssh` do sistema,
que já têm a identidade do dono. SSH_AUTH_SOCK só entra com opt-in (ssh_agent) e só no caminho ssh.
"""
from __future__ import annotations

import os
import shlex
import subprocess  # noqa: S404 — argv fixo, sem shell=True; o cmd vai como UM arg p/ `bash -lc`
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_CONTROL_PERSIST = 300        # segundos que o ControlMaster fica vivo após a última conexão
_CONNECT_TIMEOUT = 10         # falha rápido se o host não responde
_MAX_OUTPUT = 200_000         # teto da saída remota devolvida ao modelo (anti-OOM / anti-inundar contexto)
_VALID_VIA = ("tailscale", "ssh")


@dataclass
class RemoteResult:
    returncode: int
    output: str


def _check_host(host: str) -> str:
    """Valida o host ANTES de virar argv. Um host começando com '-' seria interpretado por ssh/tailscale
    como OPÇÃO (ex.: `-oProxyCommand=…` = execução de comando LOCAL) → injeção de argumento. Espaço/quebra
    de linha também são recusados. Devolve o host limpo ou levanta ValueError."""
    h = (host or "").strip()
    if not h:
        raise ValueError("host vazio.")
    if h.startswith("-"):
        raise ValueError(f"host inválido (começa com '-' → risco de injeção de argumento ssh): {h!r}")
    if any(c.isspace() for c in h):
        raise ValueError(f"host inválido (contém espaço/quebra de linha): {h!r}")
    return h


def _control_socket(alias: str, host: str) -> str:
    """Path ESTÁVEL do socket do ControlMaster (reuso de conexão). Curto pra não estourar o limite de
    104 chars de socket no macOS."""
    import hashlib

    from okami.home import okami_home
    d = okami_home() / "remote-ctl"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        d = Path("/tmp")  # noqa: S108 — fallback best-effort p/ o socket de controle
    h = hashlib.sha256(f"{alias}|{host}".encode()).hexdigest()[:12]
    return str(d / f"cm-{h}.sock")


@dataclass
class RemoteTarget:
    alias: str
    host: str
    via: str = "tailscale"               # tailscale (primário) | ssh (fallback)
    cwd: str = ""                         # diretório de trabalho remoto (cd antes de cada comando)
    ssh_agent: bool = False               # opt-in: passa SSH_AUTH_SOCK (só no caminho ssh)
    runner: Callable | None = None        # injetável p/ teste; None → subprocess.run (resolvido em call-time)
    timeout: int = 120

    @property
    def _run_fn(self) -> Callable:
        return self.runner or subprocess.run

    def base_argv(self) -> list[str]:
        """Prefixo do comando: `tailscale ssh <host>` ou `ssh -o … <host>` (com ControlMaster)."""
        _check_host(self.host)               # defesa em profundidade: host hostil (config) não vira argv
        if self.via == "tailscale":
            return ["tailscale", "ssh", self.host]
        if self.via == "ssh":
            sock = _control_socket(self.alias, self.host)
            return ["ssh",
                    "-o", f"ControlPath={sock}",
                    "-o", "ControlMaster=auto",
                    "-o", f"ControlPersist={_CONTROL_PERSIST}",
                    "-o", "BatchMode=yes",                      # nunca trava pedindo senha interativa
                    "-o", "StrictHostKeyChecking=accept-new",
                    "-o", f"ConnectTimeout={_CONNECT_TIMEOUT}",
                    self.host]
        raise ValueError(f"via inválido: {self.via!r} (use 'tailscale' ou 'ssh')")

    def build_argv(self, cmd: str) -> list[str]:
        """argv completo: prefixo + `bash -lc <cmd>`. O `cmd` vai como UM argumento (sem shell local) →
        sem quoting/injeção do lado de cá; o `bash -lc` REMOTO é que interpreta (intencional)."""
        final = f"cd {shlex.quote(self.cwd)} && {cmd}" if self.cwd else cmd
        return [*self.base_argv(), "bash", "-lc", final]

    def _env(self) -> dict:
        """Ambiente MÍNIMO do subprocess (não vaza o env do agente). PATH/HOME p/ achar tailscale/ssh;
        SSH_AUTH_SOCK só com opt-in e só no caminho ssh (default seguro = sem o agent)."""
        env = {k: os.environ[k] for k in ("PATH", "HOME") if k in os.environ}
        if self.ssh_agent and self.via == "ssh":
            sock = os.environ.get("SSH_AUTH_SOCK")
            if sock:
                env["SSH_AUTH_SOCK"] = sock
        return env

    def run(self, cmd: str, *, timeout: int | None = None, stdin: str | None = None) -> RemoteResult:
        """Roda `cmd` no host remoto. `stdin` (opc) vai pro processo (conteúdo de write não entra no argv).
        Devolve RemoteResult(returncode, output). Nunca levanta."""
        to = timeout if timeout is not None else self.timeout    # 0 é válido (timeout imediato) ≠ None (usa default)
        argv = self.build_argv(cmd)
        try:
            r = self._run_fn(argv, capture_output=True, text=True, timeout=to, env=self._env(), input=stdin)
        except subprocess.TimeoutExpired:
            return RemoteResult(124, f"[remoto: comando passou de {to}s e foi cortado]")
        except FileNotFoundError as e:                  # tailscale/ssh não instalado
            return RemoteResult(127, f"[remoto: binário não encontrado: {e}]")
        out = (getattr(r, "stdout", "") or "") + (getattr(r, "stderr", "") or "")
        if len(out) > _MAX_OUTPUT:               # comando remoto cuspindo GB não inunda RAM/contexto
            out = out[:_MAX_OUTPUT] + f"\n[… saída remota truncada em {_MAX_OUTPUT} chars]"
        return RemoteResult(getattr(r, "returncode", 1), out)

    # ── primitivos de ARQUIVO (Phase 2): as tools de FS roteiam pra cá quando conectado ──
    def read(self, path: str) -> RemoteResult:
        """Lê um arquivo remoto (cat). returncode != 0 = não existe / sem permissão."""
        return self.run(f"cat -- {shlex.quote(path)}")

    def write(self, path: str, content: str) -> RemoteResult:
        """Escreve um arquivo remoto de forma ATÔMICA (tmp + mv). Conteúdo via STDIN — nunca no argv
        (sem limite de tamanho, sem quoting/injeção)."""
        q = shlex.quote(path)
        return self.run(f't=$(mktemp) && cat > "$t" && mv -- "$t" {q}', stdin=content)

    def list(self, path: str) -> RemoteResult:
        """Lista um diretório remoto (ls -1Ap: um por linha, oculta '.'/'..', marca '/' em dir)."""
        return self.run(f"ls -1Ap -- {shlex.quote(path)}")

    def exists(self, path: str) -> bool:
        r = self.run(f"test -e {shlex.quote(path)} && echo OKAMI_Y || echo OKAMI_N")
        return "OKAMI_Y" in r.output

    def health_check(self) -> RemoteResult:
        """Testa a conexão (echo) — usado no connect p/ falhar cedo se host/config estiver errado."""
        return self.run("echo okami-remote-ok", timeout=_CONNECT_TIMEOUT + 5)

    def close(self) -> None:
        """Fecha o ControlMaster (só no caminho ssh). Best-effort."""
        if self.via != "ssh":
            return
        try:
            sock = _control_socket(self.alias, self.host)
            self._run_fn(["ssh", "-o", f"ControlPath={sock}", "-O", "exit", self.host],
                        capture_output=True, text=True, timeout=5, env=self._env())
        except Exception:  # noqa: BLE001 — fechar conexão nunca derruba nada
            pass


def resolve_remote(remote_cfg: dict | None, target: str, *, is_terminal: bool,
                   runner: Callable | None = None) -> RemoteTarget:
    """Traduz `target` (alias OU host cru) num RemoteTarget, aplicando a ALLOWLIST por superfície.

    Alias em `remote.hosts` → sempre liberado (terminal ou remoto). Host CRU (fora da lista) → só no
    TERMINAL (dono presente); numa superfície remota é RECUSADO (a allowlist é a barreira). Host com '@'
    assume ssh; nome puro assume tailscale."""
    remote_cfg = remote_cfg or {}
    hosts = remote_cfg.get("hosts")
    hosts = hosts if isinstance(hosts, dict) else {}   # #9: config malformado (lista/None) não quebra
    ssh_agent = bool(remote_cfg.get("ssh_agent"))
    target = (target or "").strip()
    if not target:
        raise ValueError("informe um alias ou host (ex.: prod, user@host).")
    spec = hosts.get(target)
    if isinstance(spec, dict):
        return RemoteTarget(alias=target, host=str(spec.get("host") or target),
                            via=str(spec.get("via") or "tailscale"),
                            cwd=str(spec.get("cwd") or ""),
                            ssh_agent=ssh_agent, runner=runner)
    if not is_terminal:                              # host cru numa superfície remota → allowlist barra
        raise ValueError(
            f"'{target}' não está em remote.hosts (allowlist) e a superfície é remota — bloqueado. "
            "Adicione com `okami remote add <alias> <host>`, ou conecte a partir do terminal.")
    _check_host(target)                              # injeção de argumento ssh (host começando com '-')
    via = "ssh" if "@" in target else "tailscale"    # heurística: user@host → ssh; nome → tailscale
    return RemoteTarget(alias=target, host=target, via=via, ssh_agent=ssh_agent, runner=runner)
