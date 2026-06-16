"""OAuth 2.1 + PKCE p/ servidores MCP (#11, port do Hermes tools/mcp_oauth.py).

Alguns MCP usam OAuth (GitHub/Google-backed) em vez de bearer estático. Aqui: PKCE (S256), monta a URL
de autorização, troca o code por token, faz refresh, e persiste tokens em ~/.okami/mcp/oauth/<server>.json.
O passo interativo (abre browser + servidor de callback efêmero no localhost) é um wrapper fino que
amarra essas peças. Core puro (testável) separado do I/O de rede/browser.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from pathlib import Path
from urllib.parse import urlencode


def generate_pkce() -> tuple[str, str, str]:
    """(code_verifier, code_challenge, method='S256') — RFC 7636. verifier 43–128 chars base64url."""
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge, "S256"


def build_authorization_url(auth_endpoint: str, *, client_id: str, redirect_uri: str, challenge: str,
                            scope: str = "", state: str = "") -> str:
    """URL do authorization endpoint com response_type=code + PKCE S256."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if scope:
        params["scope"] = scope
    if state:
        params["state"] = state
    sep = "&" if "?" in auth_endpoint else "?"
    return f"{auth_endpoint}{sep}{urlencode(params)}"


def _http_post_form(url: str, data: dict) -> dict:
    """POST form-urlencoded → JSON (default real). Injetável nos testes via `_post`."""
    import urllib.request
    body = urlencode(data).encode()
    req = urllib.request.Request(  # noqa: S310 — endpoint OAuth do servidor MCP configurado pelo dono
        url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded",
                                 "Accept": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return json.loads(resp.read())


def exchange_code(token_endpoint: str, *, client_id: str, code: str, verifier: str, redirect_uri: str,
                  _post=_http_post_form) -> dict:
    """Troca o authorization code por tokens (authorization_code grant + PKCE verifier)."""
    return _post(token_endpoint, {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
    })


def refresh_token(token_endpoint: str, *, client_id: str, refresh_token: str, _post=_http_post_form) -> dict:
    """Renova o access token via refresh_token grant."""
    return _post(token_endpoint, {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    })


class TokenStore:
    """Cache em disco dos tokens OAuth por servidor MCP (~/.okami/mcp/oauth/<server>.json, 0600)."""

    def __init__(self, root):
        self.root = Path(root)

    def _path(self, server: str) -> Path:
        safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in server)
        return self.root / f"{safe}.json"

    def save(self, server: str, tokens: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        p = self._path(server)
        p.write_text(json.dumps(tokens, ensure_ascii=False), encoding="utf-8")
        try:
            p.chmod(0o600)
        except OSError:
            pass

    def load(self, server: str) -> dict | None:
        try:
            return json.loads(self._path(server).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def valid_access_token(self, server: str, *, now: float) -> str | None:
        """access_token se existe e não expirou (margem de 30s), senão None (caller deve dar refresh)."""
        tok = self.load(server)
        if not tok or not tok.get("access_token"):
            return None
        exp = tok.get("expires_at")
        if exp is not None and float(exp) <= now + 30:
            return None
        return tok["access_token"]


def oauth_bearer(server: str, conf: dict, store: "TokenStore", *, now: float, _post=_http_post_form) -> str | None:
    """Resolve um access token válido p/ o MCP `server`: usa o do disco se fresco; se expirou e há
    refresh_token + token_endpoint no conf, faz refresh e persiste. None se não dá (precisa autorizar)."""
    tok = store.valid_access_token(server, now=now)
    if tok:
        return tok
    saved = store.load(server) or {}
    rt = saved.get("refresh_token")
    oauth = (conf or {}).get("oauth") or {}
    token_endpoint = oauth.get("token_endpoint")
    client_id = oauth.get("client_id")
    if rt and token_endpoint and client_id:
        try:
            new = refresh_token(token_endpoint, client_id=client_id, refresh_token=rt, _post=_post)
        except Exception:  # noqa: BLE001 — refresh falhou → caller re-autoriza
            return None
        if new.get("access_token"):
            if "expires_in" in new:
                new["expires_at"] = now + float(new["expires_in"])
            new.setdefault("refresh_token", rt)        # alguns IdP não re-emitem o refresh
            store.save(server, new)
            return new["access_token"]
    return None


def authorize_interactive(server: str, conf: dict, store: "TokenStore", *, port: int = 8765,
                          open_browser=None, now_fn=None) -> bool:
    """Fluxo PKCE interativo: abre o browser no authorization endpoint + sobe um servidor de callback
    efêmero no localhost p/ pegar o code, troca por token e persiste. Best-effort (depende de browser +
    porta livre); devolve True se autorizou. NÃO levanta — usado fora do hot-path."""
    import threading
    import time as _t
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    oauth = (conf or {}).get("oauth") or {}
    auth_ep, token_ep, client_id = oauth.get("authorization_endpoint"), oauth.get("token_endpoint"), oauth.get("client_id")
    if not (auth_ep and token_ep and client_id):
        return False
    verifier, challenge, _ = generate_pkce()
    state = secrets.token_urlsafe(16)
    redirect_uri = f"http://localhost:{port}/callback"
    holder: dict = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = parse_qs(urlparse(self.path).query)
            holder["code"] = (q.get("code") or [None])[0]
            holder["state"] = (q.get("state") or [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Okami: autorizacao recebida, pode fechar esta aba.")

        def log_message(self, *a):  # silencia o log do http.server
            return

    try:
        httpd = HTTPServer(("localhost", port), _Handler)
    except OSError:
        return False
    threading.Thread(target=httpd.handle_request, daemon=True).start()
    url = build_authorization_url(auth_ep, client_id=client_id, redirect_uri=redirect_uri,
                                  challenge=challenge, scope=oauth.get("scope", ""), state=state)
    (open_browser or webbrowser.open)(url)
    deadline = (now_fn or _t.time)() + 180
    while not holder.get("code") and (now_fn or _t.time)() < deadline:
        _t.sleep(0.2)
    httpd.server_close()
    if not holder.get("code") or holder.get("state") != state:
        return False
    try:
        tok = exchange_code(token_ep, client_id=client_id, code=holder["code"], verifier=verifier,
                            redirect_uri=redirect_uri)
    except Exception:  # noqa: BLE001
        return False
    if "expires_in" in tok:
        tok["expires_at"] = (now_fn or _t.time)() + float(tok["expires_in"])
    store.save(server, tok)
    return bool(tok.get("access_token"))


__all__ = ["generate_pkce", "build_authorization_url", "exchange_code", "refresh_token", "TokenStore",
           "oauth_bearer", "authorize_interactive"]
