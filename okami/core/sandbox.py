"""Sandbox de execução do `run_shell` — P0 #2 do self-review (perfis de execução).

DOIS backends, porque a GARANTIA é diferente de verdade:

  • local  (default, sempre disponível) — "cercas fortes contra acidente e exfiltração casual":
      cwd=workspace · env SANITIZADO · TIMEOUT (relógio) · TETO DE SAÍDA · rlimits OPCIONAIS
      (CPU/memória/nº de processos/tamanho de arquivo). NÃO confina o filesystem de verdade
      (`cat /etc/passwd` ainda lê) NEM bloqueia a rede de verdade — isso exige namespaces/cgroups.
      Protege contra: loop infinito (timeout), saída gigante (cap), vazamento de credencial (env),
      e — se você LIGAR os rlimits — fork-bomb/OOM/arquivo gigante.
      ⚠ rlimits vêm DESLIGADOS por padrão de propósito: RLIMIT_AS quebraria node/cargo/jvm (reservam
      memória virtual enorme). Ligue só com consciência; p/ teto de memória REAL, use o backend docker.

  • docker (opt-in) — ISOLAMENTO REAL: só o workspace montado, `--network none`, cgroups
      (--memory/--cpus/--pids-limit), usuário não-root, rootfs read-only, no-new-privileges. Código
      hostil gerado NÃO escapa. Custo: precisa do Docker no ar, parte mais devagar, imagem com as ferramentas.

Perfil (mode) → política: `read-only` bloqueia comando que MUTA (e monta o workspace `:ro` no docker);
`workspace-write` é o normal; `yolo` libera a rede também. Timeout e cap valem sempre.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SandboxPolicy:
    backend: str = "local"           # "local" | "docker" | "auto" (docker se houver, senão local)
    mode: str = "workspace-write"    # "read-only" | "workspace-write" | "yolo"
    network: bool = False            # rede liberada? (real só no docker; yolo liga)
    timeout: int = 60                # segundos (relógio) — sempre vale
    max_output: int = 100_000        # bytes de stdout+stderr devolvidos ao modelo — sempre vale
    mem_mb: int = 0                  # rlimit AS / docker --memory  (0 = não setar rlimit local)
    cpu_seconds: int = 0             # rlimit CPU                   (0 = não setar; confia no timeout)
    nproc: int = 0                   # rlimit NPROC / docker --pids-limit (0 = não setar local)
    fsize_mb: int = 0                # rlimit FSIZE                 (0 = não setar)
    image: str = "python:3.11-slim"  # imagem do backend docker
    egress_allow: tuple = ()         # allowlist de egress (hosts) via proxy filtrante (#5)
    require_isolation: bool = False   # estrito (#P1.2): exposto SEM Docker → shell/process DESABILITADO (não degrada)

    @classmethod
    def from_config(cls, d: dict | None) -> "SandboxPolicy":
        """Constrói a política do bloco `sandbox:` do okami.yaml (campos ausentes = default).

        `profile:` é um atalho de POSTURA (#5):
          • dev (default)  — backend local: cercas contra acidente/exfiltração, sem isolamento real.
                             Pra você desenvolver na sua máquina sem precisar de Docker.
          • hardened       — backend auto (Docker se houver; SEM Docker o run_shell/process fica
                             DESABILITADO em vez de cair no local). Rede off, não-root, só workspace.
        Campos explícitos sempre vencem o atalho do profile."""
        d = d or {}
        p = cls()
        prof = str(d.get("profile", "")).lower()
        if prof in ("hardened", "hardened-strict") and d.get("backend") is None:
            p.backend = "auto"          # postura endurecida → exige isolamento real (docker) quando houver
        if prof == "hardened-strict" or d.get("require_isolation"):
            p.require_isolation = True  # #P1.2: hardened-strict NÃO degrada p/ local em superfície exposta
        for k in ("backend", "mode", "network", "timeout", "max_output",
                  "mem_mb", "cpu_seconds", "nproc", "fsize_mb", "image"):
            if d.get(k) is not None:
                setattr(p, k, d[k])
        if d.get("egress_allow"):
            p.egress_allow = tuple(d["egress_allow"])
            p.network = True            # allowlist de egress implica rede (mas FILTRADA pelo proxy)
        if p.mode == "yolo":
            p.network = True            # yolo = sem freios → rede liberada também
        return p

    @property
    def network_on(self) -> bool:
        """Rede liberada? (yolo sempre libera, mesmo se a policy foi construída na mão)."""
        return self.network or self.mode == "yolo"

    def effective_backend(self) -> str:
        """Resolve o backend real (#4): 'auto' vira docker se houver Docker, senão local."""
        if self.backend == "auto":
            return "docker" if shutil.which("docker") else "local"
        return self.backend


def default_policy() -> SandboxPolicy:
    return SandboxPolicy()


# Superfícies EXPOSTAS (remoto/rede) → postura endurecida por padrão (#P1.1). CLI = máquina do dono = dev.
EXPOSED_SURFACES = frozenset({"telegram", "group", "paperclip", "slack", "discord", "mattermost",
                              "api", "gateway"})


def is_exposed(surface: str) -> bool:
    """Superfície exposta (remoto/rede)? Cobre TODOS os papéis do Paperclip (#P1).

    Sem isto, o split por papel (paperclip-worker/-manager/…) deixava o worker REMOTO fora do
    endurecimento por superfície — só o literal 'paperclip' casava. `startswith` fecha esse buraco."""
    s = str(surface or "")
    return s in EXPOSED_SURFACES or s.startswith("paperclip")


def effective_sandbox(cfg_sandbox, surface: str = "") -> "SandboxPolicy":
    """Política do run_shell/process_start CIENTE DA SUPERFÍCIE (#P1.1).

    Superfície exposta (Telegram/grupo/Paperclip/API…) SEM config explícita de backend/profile →
    endurece p/ `auto` (Docker se houver; degrada p/ local se não houver — não quebra quem não tem
    Docker). CLI local segue `dev`. Config EXPLÍCITA (backend ou profile no okami.yaml) sempre vence."""
    raw = dict(cfg_sandbox or {})
    p = SandboxPolicy.from_config(raw)
    explicit = ("backend" in raw) or ("profile" in raw)
    exposed = is_exposed(surface)
    if exposed and p.require_isolation:
        p.backend = "docker"        # #P1.2 estrito: exige Docker; sem Docker → run_shell/process DESABILITADO
    elif exposed and not explicit:
        p.backend = "auto"          # dev-friendly: endurece, mas degrada p/ local se não houver Docker
    return p


@dataclass
class SandboxResult:
    returncode: int
    output: str
    timed_out: bool = False


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[saída truncada em {limit:,} bytes]"


def _rlimit_preexec(policy: SandboxPolicy):
    """preexec_fn POSIX que aplica SÓ os rlimits ligados (>0). None se nada a setar (sem fork-hook
    → sem o aviso de thread-safety do subprocess no caso comum)."""
    if os.name != "posix":
        return None
    try:
        import resource
    except ImportError:
        return None
    limits = []
    if policy.cpu_seconds > 0:
        limits.append((resource.RLIMIT_CPU, policy.cpu_seconds))
    if policy.mem_mb > 0:
        limits.append((resource.RLIMIT_AS, policy.mem_mb * 1024 * 1024))
    if policy.fsize_mb > 0:
        limits.append((resource.RLIMIT_FSIZE, policy.fsize_mb * 1024 * 1024))
    if policy.nproc > 0 and hasattr(resource, "RLIMIT_NPROC"):
        limits.append((resource.RLIMIT_NPROC, policy.nproc))
    if not limits:
        return None

    def _apply():  # roda no FILHO, antes do exec
        for res, val in limits:
            try:
                resource.setrlimit(res, (val, val))
            except (ValueError, OSError):
                pass
    return _apply


def _host_user() -> str:
    """uid:gid do processo host → roda NÃO-ROOT no container E mantém a posse certa do workspace montado."""
    if os.name != "posix":
        return ""
    try:
        return f"{os.getuid()}:{os.getgid()}"
    except AttributeError:
        return ""


def docker_argv(cmd: str, workspace: Path, policy: SandboxPolicy, *, name: str = "") -> list[str]:
    """argv do `docker run` — PURA, p/ testar a política sem subir container.

    Postura (#5): só o workspace montado (`-v ws:/workspace`, `:ro` em read-only), `--network none`
    por padrão (rede off), cgroups (--memory/--pids-limit/--cpus), NÃO-ROOT (--user uid:gid),
    no-new-privileges, e rootfs read-only no perfil read-only."""
    ws = str(Path(workspace).resolve())
    ro = policy.mode == "read-only"
    argv = ["docker", "run", "--rm", "--init"]
    if name:
        argv += ["--name", name]                                  # nomeia p/ kill determinístico (process_start)
    argv += [
        "--network", ("bridge" if policy.network_on else "none"),  # rede OFF por padrão
        "--memory", f"{policy.mem_mb or 1024}m",
        "--pids-limit", str(policy.nproc or 256),
        "--cpus", "1",
        "--cap-drop", "ALL",                                      # nenhuma capability extra
        "--security-opt", "no-new-privileges",
    ]
    user = _host_user()
    if user:
        argv += ["--user", user]                                  # não-root (uid:gid do host)
    if ro:
        argv += ["--read-only"]                                   # rootfs read-only
    argv += [
        "-v", f"{ws}:/workspace" + (":ro" if ro else ""),
        "-w", "/workspace",
        policy.image, "sh", "-lc", cmd,
    ]
    return argv


def run_sandboxed(cmd: str, workspace: Path, policy: SandboxPolicy | None = None,
                  *, env: dict | None = None) -> SandboxResult:
    """Executa `cmd` sob a política. docker se backend=docker E docker presente; senão local."""
    policy = policy or default_policy()
    eff = policy.effective_backend()
    if eff == "docker" and not shutil.which("docker"):
        # backend docker EXPLÍCITO sem Docker → NÃO cai no local inseguro em silêncio (review #4):
        # run_shell fica desabilitado até ter o isolamento real.
        return SandboxResult(126, "sandbox: backend=docker exigido, mas Docker não está disponível — "
                             "run_shell DESABILITADO (não caio no local inseguro). Instale o Docker, "
                             "ou use backend=auto (cai no local) / backend=local explícito.")
    use_docker = (eff == "docker")
    proxy = None
    try:
        if use_docker:
            r = subprocess.run(docker_argv(cmd, workspace, policy),
                               capture_output=True, text=True, timeout=policy.timeout)
        else:
            if env is None:
                from okami.core.tools import sanitized_env
                env = sanitized_env()
            if policy.egress_allow:                 # #5: egress só p/ a allowlist, via proxy filtrante
                from okami.core.egress_proxy import EgressProxy
                proxy = EgressProxy(policy.egress_allow)
                proxy.start()
                env = {**env, **proxy.proxy_env()}  # curl/pip/npm/requests passam pelo filtro
            # shell=True é o PROPÓSITO do sandbox local (rodar o comando); a defesa é o backend docker, não evitar shell.
            r = subprocess.run(  # nosec B602
                cmd, shell=True, cwd=str(workspace), capture_output=True, text=True,  # nosemgrep — sandbox (ver # nosec acima)
                timeout=policy.timeout, env=env, preexec_fn=_rlimit_preexec(policy),
            )
    except subprocess.TimeoutExpired:
        return SandboxResult(124, f"timeout ({policy.timeout}s): {cmd}", timed_out=True)
    finally:
        if proxy is not None:
            proxy.stop()
    out = ((r.stdout or "") + (r.stderr or "")).strip() or "(sem saída)"
    return SandboxResult(r.returncode, _cap(out, policy.max_output))
