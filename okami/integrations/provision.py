"""Provisão remota — o agente bootstrappa o PRÓPRIO acesso (SSH + GitHub) numa VPS limpa, dirigido pelo
dono por um canal (Telegram). É o caminho SANCIONADO (como `store_secret` é pro `.env` bloqueado): escreve
em `~/.ssh` e configura git auth, furando o jail `_SENSITIVE_PATH` SÓ aqui, e só por trás de aprovação.

Princípios: segredo (chave privada, token) NUNCA é retornado/logado — só confirma por fingerprint/nome.
Tudo file-based (credential helper grava ~/.git-credentials) p/ funcionar mesmo com env sanitizado no shell.
`home` e `run_fn` são injetáveis → testável sem mexer no ~ real nem na rede.
"""
from __future__ import annotations

import os
import re
import subprocess  # nosec B404 — provisão roda comandos FIXOS (ssh-keygen/git/ssh-keyscan), args validados
from pathlib import Path

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")          # nome de arquivo de chave: sem traversal/espaço
_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")        # host p/ keyscan/url: sem '-' líder vira flag ssh


def _home(home: Path | None = None) -> Path:
    return Path(home or os.environ.get("OKAMI_PROVISION_HOME") or Path.home())


def _run(argv: list[str], *, stdin: str | None = None, timeout: int = 30, env: dict | None = None) -> tuple[int, str]:
    """Roda um comando FIXO de provisão. Devolve (rc, saída combinada). Nunca levanta por exit≠0."""
    try:
        p = subprocess.run(argv, input=stdin, capture_output=True, text=True,  # nosec B603 — argv fixo+validado
                           timeout=timeout, check=False, env=env)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 127, f"{type(e).__name__}: {e}"


def _gitenv(home: Path | None) -> dict:
    """Env p/ `git config --global` cair no MESMO home das credenciais (≠ poluir ~/.gitconfig real)."""
    return {**os.environ, "HOME": str(_home(home))}


def ssh_dir(home: Path | None = None) -> Path:
    d = _home(home) / ".ssh"
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        d.chmod(0o700)                                    # garante 0700 mesmo se a pasta já existia frouxa
    except OSError:
        pass
    return d


def _safe_name(name: str) -> str:
    name = (name or "id_ed25519").strip()
    if not _NAME_RE.match(name) or name in (".", ".."):
        raise ValueError(f"nome de chave inválido: {name!r} (use [A-Za-z0-9._-])")
    return name


def public_key(name: str = "id_ed25519", home: Path | None = None) -> str:
    pub = ssh_dir(home) / f"{_safe_name(name)}.pub"
    return pub.read_text(encoding="utf-8").strip() if pub.is_file() else ""


def fingerprint(name: str = "id_ed25519", home: Path | None = None, run_fn=None) -> str:
    priv = ssh_dir(home) / _safe_name(name)
    if not priv.is_file():
        return ""
    rc, out = (run_fn or _run)(["ssh-keygen", "-lf", str(priv)])
    return out.strip() if rc == 0 else ""


def generate_ssh_key(name: str = "id_ed25519", comment: str = "okami-agent",
                     home: Path | None = None, run_fn=None) -> dict:
    """Gera uma ed25519 SEM passphrase (não-interativo) se ainda não existir. Idempotente: chave existente
    NÃO é sobrescrita. Devolve {created, public_key, fingerprint, path} — só material PÚBLICO."""
    name = _safe_name(name)
    d = ssh_dir(home)
    priv = d / name
    if priv.exists():
        return {"created": False, "public_key": public_key(name, home),
                "fingerprint": fingerprint(name, home, run_fn), "path": str(priv)}
    rc, out = (run_fn or _run)(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(priv)])
    if rc != 0:
        raise RuntimeError(f"ssh-keygen falhou: {out[:200]}")
    try:
        priv.chmod(0o600)
    except OSError:
        pass
    return {"created": True, "public_key": public_key(name, home),
            "fingerprint": fingerprint(name, home, run_fn), "path": str(priv)}


def import_private_key(material: str, name: str = "id_ed25519", home: Path | None = None, run_fn=None) -> dict:
    """Grava uma chave privada que o DONO mandou (0600) e deriva a .pub. `material` NUNCA é retornado.
    Devolve {imported, public_key, fingerprint, path}."""
    name = _safe_name(name)
    if not (material or "").strip():
        raise ValueError("chave privada vazia.")
    text = material if material.endswith("\n") else material + "\n"
    d = ssh_dir(home)
    priv = d / name
    priv.write_text(text, encoding="utf-8")
    try:
        priv.chmod(0o600)
    except OSError:
        pass
    rc, out = (run_fn or _run)(["ssh-keygen", "-y", "-f", str(priv)])   # deriva a pública da privada
    if rc == 0 and out.strip():
        (d / f"{name}.pub").write_text(out.strip() + "\n", encoding="utf-8")
    return {"imported": True, "public_key": public_key(name, home),
            "fingerprint": fingerprint(name, home, run_fn), "path": str(priv)}


def known_host(host: str, home: Path | None = None, run_fn=None) -> dict:
    """ssh-keyscan do host → append (dedupe) em ~/.ssh/known_hosts. Faz o ssh não-interativo não travar no
    prompt de fingerprint. Devolve {added, host}."""
    host = (host or "").strip()
    if not _HOST_RE.match(host):
        raise ValueError(f"host inválido: {host!r}")
    rc, out = (run_fn or _run)(["ssh-keyscan", "-T", "10", host])
    lines = [ln for ln in out.splitlines() if ln and not ln.startswith("#")]
    if rc != 0 or not lines:
        return {"added": False, "host": host}
    kh = ssh_dir(home) / "known_hosts"
    existing = kh.read_text(encoding="utf-8") if kh.is_file() else ""
    have = set(existing.splitlines())
    new = [ln for ln in lines if ln not in have]
    if new:
        with kh.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write("\n".join(new) + "\n")
        try:
            kh.chmod(0o600)
        except OSError:
            pass
    return {"added": bool(new), "host": host}


def configure_git_token(token: str, *, user_name: str = "", user_email: str = "", host: str = "github.com",
                        home: Path | None = None, run_fn=None) -> dict:
    """Configura git p/ HTTPS auth com PAT, FILE-BASED: credential.helper store + ~/.git-credentials.
    Sobrevive ao env sanitizado do shell (≠ depender de GITHUB_TOKEN na env). `token` NUNCA é retornado.
    Devolve {host, method:'token', user_name, user_email} — sem o segredo."""
    if not (token or "").strip():
        raise ValueError("token vazio.")
    if not _HOST_RE.match(host):
        raise ValueError(f"host inválido: {host!r}")
    run = run_fn or _run
    cred = _home(home) / ".git-credentials"
    line = f"https://x-access-token:{token}@{host}"
    existing = cred.read_text(encoding="utf-8").splitlines() if cred.is_file() else []
    kept = [ln for ln in existing if ln.strip() and f"@{host}" not in ln]   # substitui a credencial do mesmo host
    cred.write_text("\n".join([*kept, line]) + "\n", encoding="utf-8")
    try:
        cred.chmod(0o600)
    except OSError:
        pass
    genv = _gitenv(home)
    run(["git", "config", "--global", "credential.helper", "store"], env=genv)
    if user_name:
        run(["git", "config", "--global", "user.name", user_name], env=genv)
    if user_email:
        run(["git", "config", "--global", "user.email", user_email], env=genv)
    return {"host": host, "method": "token", "user_name": user_name, "user_email": user_email,
            "credentials_file": str(cred)}


def configure_git_ssh(*, host: str = "github.com", home: Path | None = None, run_fn=None) -> dict:
    """Faz o git falar SSH com o host (usa a chave provisionada): url.insteadOf reescreve https://host/ →
    git@host:. Assim qualquer `git clone/push https://github.com/...` vira SSH transparentemente."""
    if not _HOST_RE.match(host):
        raise ValueError(f"host inválido: {host!r}")
    (run_fn or _run)(["git", "config", "--global", f"url.git@{host}:.insteadOf", f"https://{host}/"],
                     env=_gitenv(home))
    return {"host": host, "method": "ssh"}


def git_auth_status(home: Path | None = None, run_fn=None) -> dict:
    """Estado da auth SEM revelar segredo: tem ~/.git-credentials (e p/ quais hosts), credential.helper,
    user.name/email, e quais chaves SSH existem (só nomes + fingerprints)."""
    run = run_fn or _run
    h = _home(home)
    cred = h / ".git-credentials"
    hosts = []
    if cred.is_file():
        for ln in cred.read_text(encoding="utf-8").splitlines():
            m = re.search(r"@([A-Za-z0-9._:-]+)\s*$", ln.strip())
            if m:
                hosts.append(m.group(1))
    genv = _gitenv(home)
    rc_n, name = run(["git", "config", "--global", "user.name"], env=genv)
    rc_e, email = run(["git", "config", "--global", "user.email"], env=genv)
    keys = []
    d = h / ".ssh"
    if d.is_dir():
        for pub in sorted(d.glob("*.pub")):
            keys.append({"name": pub.stem, "fingerprint": fingerprint(pub.stem, home, run_fn)})
    return {"token_hosts": hosts, "user_name": name.strip() if rc_n == 0 else "",
            "user_email": email.strip() if rc_e == 0 else "", "ssh_keys": keys}


def verify(host: str = "github.com", home: Path | None = None, run_fn=None) -> dict:
    """Testa o acesso ao GitHub sem alterar nada: `ssh -T git@host` (SSH) e `git ls-remote` HTTPS via
    credential helper. Devolve {ssh_ok, ssh_msg, https_ok}. Best-effort (rede pode faltar)."""
    if not _HOST_RE.match(host):
        raise ValueError(f"host inválido: {host!r}")
    run = run_fn or _run
    env_ssh = ["ssh", "-T", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes", f"git@{host}"]
    rc_s, out_s = run(env_ssh)
    # GitHub responde "Hi <user>! You've successfully authenticated" com exit 1 (sem shell) — sucesso mesmo
    ssh_ok = "successfully authenticated" in out_s.lower()
    return {"ssh_ok": ssh_ok, "ssh_msg": out_s.strip()[:200], "host": host}


__all__ = ["ssh_dir", "public_key", "fingerprint", "generate_ssh_key", "import_private_key", "known_host",
           "configure_git_token", "configure_git_ssh", "git_auth_status", "verify"]
