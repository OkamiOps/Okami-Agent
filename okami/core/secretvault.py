"""Cofre de segredos CRIPTOGRAFADO em repouso — "Só no cofre, nunca no LLM" (diretiva do dono).

Onde o `.env` global (okami.config.set_env_secret) grava em TEXTO PLANO (0600, mas legível por
qualquer processo do dono que abra o arquivo), este cofre grava o VALOR cifrado com Fernet
(AES-128-CBC + HMAC, `cryptography.fernet`). A chave de cifragem é local-à-máquina: um arquivo de
32 bytes aleatórios em `$OKAMI_HOME/.secret_key` (0600), gerado no primeiro uso — nunca versionado,
nunca deriva de senha/segredo do usuário.

Layout em disco: `$OKAMI_HOME/secrets.vault.json` — `{"NOME": "<fernet-token-base64>", ...}`. O
NOME nunca é cifrado (é só um rótulo, tipo "GITHUB_TOKEN"); só o VALOR é.

Contrato:
  - `vault_set(name, value)` — cifra e grava (upsert).
  - `vault_get(name) -> str | None` — decifra; None se ausente/corrompido (fail-closed, nunca levanta
    pro caller — um cofre ilegível não pode travar o boot).
  - `vault_names() -> list[str]` — só os NOMES (nunca os valores) — para listagem/diagnóstico.
  - `resolve_secret(name) -> str | None` — cadeia de resolução p/ boot/tools: cofre → os.environ →
    .env (via okami.config._load_env, já carregado no import). Cofre GANHA de .env de propósito
    (é a fonte "mais nova"/mais forte que o dono escolheu ao mandar a chave pelo chat).
  - `apply_vault_to_environ()` — popula os.environ com TODO NOME do cofre que ainda não está setado
    (não-destrutivo, mesmo contrato do secret_sources.apply_secrets) — chamado no boot do gateway/
    runner para que providers.py/oauth.py (que só leem os.environ) enxerguem o cofre SEM precisar
    ser editados.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_KEY_FILE_NAME = ".secret_key"
_VAULT_FILE_NAME = "secrets.vault.json"


def _home_dir() -> Path:
    from okami.home import okami_home
    return okami_home()


def key_path() -> Path:
    return _home_dir() / _KEY_FILE_NAME


def vault_path() -> Path:
    return _home_dir() / _VAULT_FILE_NAME


def _get_or_create_key() -> bytes:
    """Chave Fernet local-à-máquina: lê `$OKAMI_HOME/.secret_key` (32 bytes urlsafe-base64 crus,
    formato que o Fernet espera) ou gera+grava (0600) no primeiro uso. NUNCA deriva de nada que o
    usuário digitou — perder o arquivo = perder o cofre (aceitável: o .env plano continua de fallback)."""
    from cryptography.fernet import Fernet

    p = key_path()
    if p.exists():
        raw = p.read_bytes().strip()
        if raw:
            return raw
    p.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    _atomic_write(p, key)
    from okami.core.platform_compat import secure_chmod
    secure_chmod(p)
    return key


def _atomic_write(path: Path, data: bytes) -> None:
    """Escrita atômica + 0600 ANTES do conteúdo tocar o disco (mesmo padrão de config.set_env_secret)."""
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".", suffix=".tmp")
    try:
        try:
            os.fchmod(fd, 0o600)
        except (AttributeError, OSError):
            pass
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        from okami.core.platform_compat import secure_chmod
        secure_chmod(path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(_get_or_create_key())


def _load_raw() -> dict:
    p = vault_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def vault_set(name: str, value: str) -> Path:
    """Cifra `value` com Fernet e grava/atualiza `name` no cofre (upsert, atômico, 0600). Devolve o
    caminho do arquivo do cofre — o VALOR nunca aparece no retorno nem em log (só o path)."""
    if not name or not isinstance(name, str):
        raise ValueError("vault_set exige um nome não-vazio")
    token = _fernet().encrypt((value or "").encode("utf-8")).decode("ascii")
    data = _load_raw()
    data[name] = token
    _atomic_write(vault_path(), json.dumps(data, indent=2, sort_keys=True).encode("utf-8"))
    return vault_path()


def vault_get(name: str) -> str | None:
    """Decifra e devolve o valor de `name`, ou None se ausente/corrompido/chave errada (fail-closed —
    nunca levanta: um cofre inacessível não pode derrubar boot/tool)."""
    data = _load_raw()
    token = data.get(name)
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:  # noqa: BLE001 — cofre corrompido/chave errada → None, não crash
        return None


def vault_names() -> list[str]:
    """Só os NOMES guardados — nunca os valores (uso em diagnóstico/listagem)."""
    return sorted(_load_raw().keys())


def resolve_secret(name: str) -> str | None:
    """Resolução em cadeia p/ auth de provider/tool: COFRE (mais forte/recente) → os.environ (já
    populado por .env via config._load_env no import) → None. NÃO edita providers.py/oauth.py — eles
    continuam lendo os.environ; `apply_vault_to_environ()` é quem faz a ponte no boot."""
    v = vault_get(name)
    if v:
        return v
    env = os.environ.get(name)
    return env if env else None


def apply_vault_to_environ(*, override: bool = True) -> dict:
    """Popula os.environ com todo NOME do cofre. `override=True` (default): o cofre GANHA de um valor
    já vindo do `.env` — mesma precedência de `resolve_secret` (cofre é a fonte MAIS FRESCA/forte: o
    dono acabou de mandar a credencial pelo chat, deve vencer um `.env` desatualizado). Isto DIFERE
    do contrato não-destrutivo de `secret_sources.apply_secrets` de propósito — passe `override=False`
    só se precisar do comportamento antigo (ex.: teste que quer um valor de ambiente fixo vencendo).
    Chamado no boot (okami.config._load_env, DEPOIS do `.env`). Fail-never-block: cofre ilegível →
    {'applied': 0, 'error': ...}, nunca exceção."""
    try:
        names = vault_names()
    except Exception as e:  # noqa: BLE001
        return {"applied": 0, "skipped": 0, "error": str(e)}
    applied = skipped = 0
    for name in names:
        if not override and os.environ.get(name):
            skipped += 1
            continue
        val = vault_get(name)
        if val:
            os.environ[name] = val
            applied += 1
    return {"applied": applied, "skipped": skipped, "error": ""}
