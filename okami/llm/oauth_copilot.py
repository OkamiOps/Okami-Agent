"""Login GitHub Copilot — device flow (client_id do VS Code) + troca pelo token curto da API.

Dois tokens em jogo, NÃO confundir:
- "github_token" (gho_/ghu_): o token OAuth de longo prazo, obtido 1x via device flow (ou já
  presente via env/gh CLI). Isso é o que guardamos no nosso store.
- "copilot token" (tgp_...): token CURTO (~minutos) devolvido pela troca em
  api.github.com/copilot_internal/v2/token — é o que de fato autentica as chamadas à API de
  chat da Copilot. Cacheado em processo, nunca salvo em disco (expira rápido, não vale a pena).

client_id `Iv1.b507a08c87ecfe98` é o GitHub App usado pelo VS Code — CONFIRMADO no Hermes.
Usar o client_id de outro app (ex.: opencode) gera um github_token que a Copilot API rejeita
na troca (token não-exchangeable), mesmo sendo um OAuth token válido do GitHub.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from okami.llm.oauth import _err_payload, load_tokens, save_tokens

CLIENT_ID = "Iv1.b507a08c87ecfe98"
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
VERIFICATION_URI = "https://github.com/login/device"
EXCHANGE_URL = "https://api.github.com/copilot_internal/v2/token"
DEFAULT_BASE_URL = "https://api.githubcopilot.com"

EDITOR_VERSION = "vscode/1.104.1"
USER_AGENT = "GitHubCopilotChat/0.26.7"

_DEVICE_PENDING = {"authorization_pending"}
_DEVICE_SLOWDOWN = {"slow_down"}

# cache em processo do token trocado (curto prazo) — nunca vai pro disco.
_exchange_cache: dict = {}


def _post_form(url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return _err_payload(e.code, e.read().decode("utf-8", "ignore"))


def copilot_login(emit: Callable[[str], None],
                  now: Callable[[], float] = time.time,
                  sleep: Callable[[float], None] = time.sleep) -> dict:
    """Device Authorization Grant contra o GitHub (RFC 8628), client_id do VS Code.

    Salva o github_token BRUTO (gho_/ghu_) no store `copilot` — a troca pelo token curto da
    API acontece depois, sob demanda, em `copilot_access_token`.
    """
    dev = _post_form(DEVICE_CODE_URL, {"client_id": CLIENT_ID, "scope": "read:user"})
    if "device_code" not in dev:
        raise RuntimeError(f"device/code falhou: {dev}")
    uri = dev.get("verification_uri") or VERIFICATION_URI
    emit(f"Abra: {uri}\nCódigo: {dev.get('user_code')}\nAguardando autorização...")

    interval = int(dev.get("interval", 5))
    deadline = now() + int(dev.get("expires_in", 900))
    while now() < deadline:
        sleep(interval)
        tok = _post_form(ACCESS_TOKEN_URL, {
            "client_id": CLIENT_ID,
            "device_code": dev["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        })
        if "access_token" in tok:
            data = {"github_token": tok["access_token"], "raw": tok}
            save_tokens("copilot", data)
            return data
        err = tok.get("error", "")
        if err in _DEVICE_SLOWDOWN:
            interval += 5
            continue
        if err in _DEVICE_PENDING:
            continue
        raise RuntimeError(f"device token erro: {tok}")
    raise RuntimeError("device login expirou")


def _gh_cli_token() -> str | None:
    """Fallback: token da sessão `gh auth login` já feita na máquina (fail-safe se gh ausente)."""
    try:
        out = subprocess.run(  # noqa: S603
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    tok = (out.stdout or "").strip()
    return tok or None


def _raw_github_token() -> str | None:
    """Ordem: nosso store → env (COPILOT_GITHUB_TOKEN > GH_TOKEN > GITHUB_TOKEN) → `gh auth token`.

    PATs clássicos (ghp_...) são REJEITADOS aqui: funcionam para a API REST do GitHub mas a
    troca copilot_internal/v2/token não os aceita (só gho_/ghu_ de OAuth Apps autorizados p/
    Copilot, e tokens de "GitHub App" que começam diferente). Melhor falhar cedo com um motivo
    claro do que deixar a troca devolver um 401 opaco.
    """
    import os

    data = load_tokens("copilot")
    candidates = []
    if data and data.get("github_token"):
        candidates.append(data["github_token"])
    for env_var in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        v = os.environ.get(env_var)
        if v:
            candidates.append(v)
    cli = _gh_cli_token()
    if cli:
        candidates.append(cli)

    for tok in candidates:
        if tok.startswith("ghp_"):
            continue  # PAT clássico: não é exchangeable, pula pro próximo candidato
        return tok
    return None


def _exchange(raw_token: str, now: float) -> dict:
    req = urllib.request.Request(EXCHANGE_URL, method="GET")
    req.add_header("Authorization", f"token {raw_token}")
    req.add_header("Editor-Version", EDITOR_VERSION)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"copilot_internal/v2/token falhou ({e.code}): {detail[:300]}") from e
    endpoints = data.get("endpoints") or {}
    result = {
        "token": data.get("token"),
        "expires_at": data.get("expires_at"),
        "base_url": endpoints.get("api") or DEFAULT_BASE_URL,
        "_fetched_at": now,
    }
    _exchange_cache.update(result)
    return result


# margem de segurança antes do expires_at real: evita usar um token na borda da expiração
# no meio de uma chamada de rede (a Copilot API já dá o token com TTL curto por si só).
_CACHE_MARGIN_S = 120


def copilot_access_token(now: Callable[[], float] = time.time) -> tuple[str, str] | tuple[None, None]:
    """Token curto válido p/ a Copilot API + base_url (enterprise-aware). Cacheado em processo."""
    ts = now()
    if _exchange_cache.get("token") and _exchange_cache.get("expires_at"):
        if _exchange_cache["expires_at"] - _CACHE_MARGIN_S > ts:
            return _exchange_cache["token"], _exchange_cache.get("base_url", DEFAULT_BASE_URL)

    raw = _raw_github_token()
    if not raw:
        return None, None
    try:
        result = _exchange(raw, ts)
    except RuntimeError:
        return None, None
    if not result.get("token"):
        return None, None
    return result["token"], result.get("base_url", DEFAULT_BASE_URL)


def copilot_base_url() -> str:
    """base_url mais recente conhecida (troca cacheada) — senão o default público."""
    return _exchange_cache.get("base_url") or DEFAULT_BASE_URL


def copilot_logged_in() -> bool:
    return load_tokens("copilot") is not None or _raw_github_token() is not None
