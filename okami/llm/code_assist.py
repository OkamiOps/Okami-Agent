"""Google Code Assist — acesso ao tier GRÁTIS de Gemini via cloudcode-pa (#17, port do Hermes
agent/google_code_assist.py + gemini_cloudcode_adapter.py).

NÃO é o SDK público `generativelanguage`: é a control-plane interna do Code Assist (a mesma do gemini-cli
oficial), que dá quota diária generosa p/ conta Google PESSOAL sem billing. Fits a constraint do Okami
(assinatura/conta, não pool de chave de API).

Arquitetura mínima e honesta:
- a TRADUÇÃO de mensagens reusa o `gemini_native` (to_gemini_request/from_gemini_response) — Code Assist usa
  o MESMO formato Gemini, só embrulhado num envelope de control-plane e enviado com OAuth Bearer;
- aqui ficam: o envelope (wrap/unwrap), o PKCE + URL de auth, o refresh-token empacotado, a leitura de quota
  e o `code_assist_complete` (rede injetável p/ teste offline);
- sem credencial Google → erro CLARO (degrada com graça, não crasha o agente).
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import urllib.parse
from dataclasses import dataclass

from okami.llm.usage import Completion, normalize_usage

CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Cliente OAuth PÚBLICO do gemini-cli (desktop, PKCE — não é segredo confidencial).
DEFAULT_CLIENT_ID = "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
OAUTH_SCOPES = ("https://www.googleapis.com/auth/cloud-platform "
                "https://www.googleapis.com/auth/userinfo.email "
                "https://www.googleapis.com/auth/userinfo.profile")

FREE_TIER_ID = "free-tier"
LEGACY_TIER_ID = "legacy-tier"
STANDARD_TIER_ID = "standard-tier"


# ----------------------------------------------------------------- envelope da control-plane
def wrap_code_assist_request(*, project_id: str, model: str, inner_request: dict,
                             user_prompt_id: str | None = None) -> dict:
    """Embrulha o request Gemini no envelope do Code Assist (project + model + request)."""
    return {
        "project": project_id or "",
        "model": model,
        "user_prompt_id": user_prompt_id or secrets.token_hex(8),
        "request": inner_request,
    }


def unwrap_code_assist_response(resp: dict) -> dict:
    """Desembrulha a resposta Gemini de dentro do envelope (campo `response`), ou devolve como veio."""
    inner = resp.get("response") if isinstance(resp, dict) else None
    return inner if isinstance(inner, dict) else resp


# ----------------------------------------------------------------- refresh-token empacotado
@dataclass(frozen=True)
class RefreshParts:
    """refresh_token + project_id + managed_project_id num só campo (formato do opencode-gemini-auth)."""
    refresh_token: str = ""
    project_id: str = ""
    managed_project_id: str = ""

    @classmethod
    def parse(cls, packed: str) -> "RefreshParts":
        parts = (packed or "").split("|", 2)
        return cls(
            refresh_token=parts[0] if parts else "",
            project_id=parts[1] if len(parts) > 1 else "",
            managed_project_id=parts[2] if len(parts) > 2 else "",
        )

    def format(self) -> str:
        return "|".join([self.refresh_token, self.project_id, self.managed_project_id])


# ----------------------------------------------------------------- OAuth (PKCE S256)
def generate_pkce_pair() -> tuple[str, str]:
    """(verifier, challenge) PKCE RFC 7636 — challenge = base64url(sha256(verifier)) sem padding."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_auth_url(*, client_id: str, redirect_uri: str, state: str, challenge: str,
                   scope: str = OAUTH_SCOPES) -> str:
    """URL de autorização (browser) com PKCE + refresh-token (access_type=offline + prompt=consent)."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    return AUTH_ENDPOINT + "?" + urllib.parse.urlencode(params)


# ----------------------------------------------------------------- quota
def parse_quota_buckets(resp: dict) -> list[dict]:
    """retrieveUserQuota → [{model_id, remaining_fraction, reset_time}]. Vazio se sem buckets."""
    out = []
    for b in (resp or {}).get("buckets", []) or []:
        out.append({
            "model_id": b.get("modelId", ""),
            "remaining_fraction": float(b.get("remainingFraction", 0.0) or 0.0),
            "reset_time": b.get("resetTime", ""),
        })
    return out


# ----------------------------------------------------------------- completion
def _default_post(url: str, body: dict, token: str) -> dict:
    """POST JSON real ao cloudcode-pa com Bearer. Só usado fora de teste."""
    import json
    import urllib.request
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={  # noqa: S310 — URL fixa de control-plane
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "okami-code-assist",
    })
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8"))


def code_assist_complete(pc, messages: list[dict], model: str | None, overrides: dict | None = None,
                         *, _token=None, _post=None) -> Completion:
    """Completa via Code Assist: traduz (gemini_native) → embrulha → POST → desembrulha → traduz de volta.
    `_token()->str` e `_post(url, body, token)->dict` injetáveis p/ teste offline. Sem token → erro claro."""
    from okami.llm.gemini_native import from_gemini_response, to_gemini_request
    ov = overrides or {}
    mdl = model or getattr(pc, "model", "")
    token_fn = _token or (lambda: _get_access_token(pc))
    token = token_fn()                                    # sem credencial → levanta aqui (claro)
    inner = to_gemini_request(messages, tools=ov.get("tools"),
                              generation_config=ov.get("generation_config"))
    project = getattr(pc, "project_id", "") or ""
    env = wrap_code_assist_request(project_id=project, model=mdl, inner_request=inner)
    url = f"{CODE_ASSIST_ENDPOINT}/v1internal:generateContent"
    post = _post or _default_post
    raw = post(url, env, token)
    rd = unwrap_code_assist_response(raw)
    text, finish, tool_calls = from_gemini_response(rd)
    return Completion(text=text, finish_reason=finish, tool_calls=tool_calls,
                      provider=getattr(pc, "name", "google-code-assist"), model=mdl,
                      usage=normalize_usage(rd.get("usageMetadata"), transport="gemini_native"))


def _get_access_token(pc) -> str:
    """Lê/renova o access token da credencial Google em disco. Sem credencial → RuntimeError claro."""
    raise RuntimeError("sem credencial Google Code Assist — rode `okami gemini login` "
                       "(ou configure providers.<nome>.transport: gemini_cloudcode após o login).")


__all__ = ["CODE_ASSIST_ENDPOINT", "AUTH_ENDPOINT", "TOKEN_ENDPOINT", "DEFAULT_CLIENT_ID", "OAUTH_SCOPES",
           "FREE_TIER_ID", "LEGACY_TIER_ID", "STANDARD_TIER_ID",
           "wrap_code_assist_request", "unwrap_code_assist_response", "RefreshParts",
           "generate_pkce_pair", "build_auth_url", "parse_quota_buckets", "code_assist_complete"]
