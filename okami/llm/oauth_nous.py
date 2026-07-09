"""Login OAuth de assinatura Nous Research (portal.nousresearch.com) — device flow RFC 8628.

Espelha o `device_login` genérico de `okami.llm.oauth`, mas o REFRESH da Nous é fora do padrão:
o refresh_token vai num HEADER próprio (`x-nous-refresh-token`), não no corpo do POST — por isso
não dá pra reusar `get_valid_token`/`force_refresh` (que só sabem body-based refresh_token).

Nous também é single-use refresh_token (rotaciona a cada troca): se o portal detectar reuso
(ex.: dois processos batendo com o mesmo refresh_token velho), devolve `refresh_token_reused` e
a sessão inteira é revogada — aqui isso é tratado como terminal: limpamos o store e sinalizamos
que é preciso logar de novo (devolve None em vez de reciclar um token morto).

Falha-segura: qualquer erro de rede/parsing devolve None/mensagem clara, nunca propaga exceção
inesperada pro chamador.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable

from okami.llm.oauth import (
    _DEVICE_PENDING,
    _DEVICE_SLOWDOWN,
    _err_payload,
    _normalize,
    _post_form,
    load_tokens,
    logout,
    save_tokens,
)

PROVIDER = "nous"

NOUS_PORTAL = "https://portal.nousresearch.com"
NOUS_CLIENT_ID = "hermes-cli"
NOUS_SCOPE = "inference:invoke"
NOUS_INFERENCE_BASE = "https://inference-api.nousresearch.com/v1"
NOUS_DEVICE_CODE_URL = f"{NOUS_PORTAL}/api/oauth/device/code"
NOUS_TOKEN_URL = f"{NOUS_PORTAL}/api/oauth/token"

# estados terminais do refresh_token: retentar com o MESMO token nunca vai funcionar — precisa relogar.
_REFRESH_TERMINAL = {"refresh_token_reused", "invalid_grant", "invalid_token"}


def nous_login(emit: Callable[[str], None],
              now: Callable[[], float] = time.time,
              sleep: Callable[[float], None] = time.sleep) -> dict:
    """Device Authorization Grant (RFC 8628) contra o portal Nous. `now`/`sleep` injetáveis p/ teste."""
    dev = _post_form(NOUS_DEVICE_CODE_URL, {"client_id": NOUS_CLIENT_ID, "scope": NOUS_SCOPE})
    if "device_code" not in dev:
        raise RuntimeError(f"device/code falhou: {dev}")
    uri = dev.get("verification_uri_complete") or dev.get("verification_uri", "(ver docs)")
    emit(f"Abra: {uri}\nCódigo: {dev.get('user_code')}\nAguardando autorização...")
    interval = int(dev.get("interval", 5))
    deadline = now() + int(dev.get("expires_in", 600))
    while now() < deadline:
        sleep(interval)
        tok = _post_form(NOUS_TOKEN_URL, {
            "client_id": NOUS_CLIENT_ID,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": dev["device_code"],
        })
        if "access_token" in tok:
            data = _normalize(tok, now())
            save_tokens(PROVIDER, data)
            return data
        err = tok.get("error", "")
        if err in _DEVICE_SLOWDOWN:
            interval += 5
            continue
        if err in _DEVICE_PENDING:
            continue
        raise RuntimeError(f"device token erro: {tok}")
    raise RuntimeError("device login expirou")


def _post_refresh(refresh_token: str) -> dict:
    """POST refresh_token grant com o refresh_token no HEADER `x-nous-refresh-token` (não no corpo —
    fora do padrão RFC 6749 clássico, é assim que a Nous exige)."""
    import urllib.parse
    body = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": NOUS_CLIENT_ID}).encode("utf-8")
    req = urllib.request.Request(NOUS_TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    req.add_header("x-nous-refresh-token", refresh_token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return _err_payload(e.code, e.read().decode("utf-8", "ignore"))


def nous_access_token(now: Callable[[], float] = time.time) -> str | None:
    """Token válido do store; refresh via header se expirado. None se preciso relogar (refresh morto)."""
    data = load_tokens(PROVIDER)
    if not data:
        return None
    if data.get("expires_at", 0) - 60 > now():
        return data.get("access_token")
    rt = data.get("refresh_token")
    if not rt:
        return data.get("access_token")  # expirado e sem refresh — melhor-esforço
    tok = _post_refresh(rt)
    if "access_token" in tok:
        new = _normalize(tok, now())
        new["refresh_token"] = new.get("refresh_token") or rt
        save_tokens(PROVIDER, new)
        return new["access_token"]
    err = tok.get("error", "")
    if err in _REFRESH_TERMINAL:
        logout(PROVIDER)  # refresh_token reusado/revogado — token morto, precisa `nous_login` de novo
        return None
    return data.get("access_token")  # falha transitória — melhor-esforço, devolve o que tem


def nous_inference_base() -> str:
    return NOUS_INFERENCE_BASE
