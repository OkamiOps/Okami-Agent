"""Google Workspace OAuth2 setup for Okami — non-interactive, driven step by step by the agent.

Commands:
  setup.py --check                             # is there a usable credential on disk?
  setup.py --client-secret /path/to.json       # store the dono's own downloaded OAuth client file
  setup.py --auth-url --services email,calendar --format json   # print the authorization URL
  setup.py --auth-code "<pasted URL or code>" --format json     # complete the exchange

Okami NEVER generates or guesses the OAuth client file (client_id/client_secret pair) — that comes
from the dono's own Google Cloud Console project, downloaded and handed to --client-secret. This
script only orchestrates the standard Authorization Code + PKCE flow against Google's published
endpoints; the one HTTP call it makes (the code-for-credential exchange) is delegated to the
generic _google_refresh_http.post_form() helper, same as the renewal path in _google_cred_store.py.

Agent workflow:
  1. Run --check. If it prints AUTHENTICATED, skip setup.
  2. Ask the dono for the client-secret file path (from Google Cloud Console). Run --client-secret PATH.
  3. Run --auth-url with the service scopes the dono actually needs. Send the printed URL to the dono.
  4. The dono opens the URL, authorizes, and is redirected to a page that will fail to load
     (localhost) — that's expected. They copy the full redirected URL (or just the code param).
  5. Run --auth-code with whatever they pasted.
  6. Run --check again to confirm.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _google_cred_store import (  # noqa: E402
    FIELD_ACCESS,
    FIELD_CLIENT_ID,
    FIELD_CLIENT_SECRET,
    FIELD_EXPIRES_IN,
    FIELD_REFRESH,
    FIELD_TOKEN_URI,
    client_secret_path,
    credential_path,
    is_expired,
    load_credential,
    missing_fields,
    save_credential,
)
from _google_urlutil import encode_query, extract_query_param  # noqa: E402
from _okami_home import get_okami_home  # noqa: E402

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "http://localhost:1"

PENDING_PATH_NAME = "google_oauth_pending.json"

SERVICE_SCOPES = {
    "email": [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
    ],
    "calendar": ["https://www.googleapis.com/auth/calendar"],
    "drive": ["https://www.googleapis.com/auth/drive"],
    "sheets": ["https://www.googleapis.com/auth/spreadsheets"],
    "docs": ["https://www.googleapis.com/auth/documents"],
    "contacts": ["https://www.googleapis.com/auth/contacts.readonly"],
}
ALL_SCOPES = sorted({scope for scopes in SERVICE_SCOPES.values() for scope in scopes})


def _pending_path() -> Path:
    return get_okami_home() / PENDING_PATH_NAME


def _print(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        for k, v in payload.items():
            print(f"{k}: {v}")


def _resolve_scopes(services: str) -> list[str]:
    if services.strip() == "all":
        return ALL_SCOPES
    wanted: list[str] = []
    for name in services.split(","):
        name = name.strip()
        if name not in SERVICE_SCOPES:
            raise SystemExit(f"unknown service '{name}' — choose from: {', '.join(SERVICE_SCOPES)}, all")
        wanted.extend(SERVICE_SCOPES[name])
    return sorted(set(wanted))


def cmd_check(as_json: bool) -> int:
    data = load_credential()
    if data is None:
        _print({"status": "NOT_AUTHENTICATED"}, as_json)
        return 1
    missing = missing_fields(data)
    if missing:
        _print({"status": "NOT_AUTHENTICATED", "reason": f"missing fields: {', '.join(missing)}"}, as_json)
        return 1
    status = "AUTHENTICATED" if not is_expired(data) else "AUTHENTICATED_EXPIRING"
    _print({"status": status}, as_json)
    return 0


def cmd_client_secret(path_str: str, as_json: bool) -> int:
    src = Path(path_str).expanduser()
    if not src.is_file():
        _print({"ok": False, "error": f"file not found: {src}"}, as_json)
        return 1
    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _print({"ok": False, "error": f"invalid JSON: {e}"}, as_json)
        return 1

    block = raw.get("installed") or raw.get("web")
    if not block or FIELD_CLIENT_ID not in block or FIELD_CLIENT_SECRET not in block:
        _print({"ok": False, "error": "file doesn't look like a Google OAuth client download"}, as_json)
        return 1

    client_secret_path().write_text(json.dumps(raw, indent=2), encoding="utf-8")
    _print({"ok": True, "saved_to": str(client_secret_path())}, as_json)
    return 0


def cmd_auth_url(services: str, as_json: bool) -> int:
    if not client_secret_path().is_file():
        _print({"ok": False, "error": "run --client-secret first"}, as_json)
        return 1
    client_block = json.loads(client_secret_path().read_text(encoding="utf-8"))
    block = client_block.get("installed") or client_block.get("web") or {}
    client_id = block.get(FIELD_CLIENT_ID)
    if not client_id:
        _print({"ok": False, "error": "stored client file has no client_id"}, as_json)
        return 1

    scopes = _resolve_scopes(services)

    verifier = secrets.token_urlsafe(64)[:64]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{AUTH_ENDPOINT}?{encode_query(params)}"

    _pending_path().write_text(
        json.dumps({"verifier": verifier, "client_id": client_id, "redirect_uri": REDIRECT_URI}, indent=2),
        encoding="utf-8",
    )
    _print({"ok": True, "auth_url": auth_url, "scopes": scopes}, as_json)
    return 0


def _extract_code(pasted: str) -> str:
    found = extract_query_param(pasted, "code")
    return found if found is not None else pasted.strip()


def cmd_auth_code(pasted: str, as_json: bool) -> int:
    if not _pending_path().is_file():
        _print({"ok": False, "error": "no pending authorization — run --auth-url first"}, as_json)
        return 1
    pending = json.loads(_pending_path().read_text(encoding="utf-8"))
    client_block = json.loads(client_secret_path().read_text(encoding="utf-8"))
    block = client_block.get("installed") or client_block.get("web") or {}

    code = _extract_code(pasted)
    payload = {
        "client_id": pending["client_id"],
        FIELD_CLIENT_SECRET: block.get(FIELD_CLIENT_SECRET, ""),
        "code": code,
        "code_verifier": pending["verifier"],
        "grant_type": "authorization_code",
        "redirect_uri": pending["redirect_uri"],
    }

    from _google_refresh_http import HttpPostError, post_form  # local import, see module docstring

    try:
        result = post_form(TOKEN_ENDPOINT, payload)
    except HttpPostError as e:
        _print({"ok": False, "error": str(e), "hint": "the code may be expired or already used — re-run --auth-url"}, as_json)
        return 1

    if FIELD_ACCESS not in result:
        _print({"ok": False, "error": f"unexpected response: {result}"}, as_json)
        return 1

    from datetime import datetime, timezone

    expiry = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + result.get(FIELD_EXPIRES_IN, 3600), tz=timezone.utc
    ).isoformat()
    stored = {
        FIELD_ACCESS: result[FIELD_ACCESS],
        FIELD_REFRESH: result.get(FIELD_REFRESH, ""),
        FIELD_CLIENT_ID: pending["client_id"],
        FIELD_CLIENT_SECRET: block.get(FIELD_CLIENT_SECRET, ""),
        FIELD_TOKEN_URI: TOKEN_ENDPOINT,
        "expiry": expiry,
    }
    save_credential(stored)
    _pending_path().unlink(missing_ok=True)

    _print({"ok": True, "saved_to": str(credential_path())}, as_json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="setup.py",
        description="Non-interactive Google Workspace OAuth2 setup (Authorization Code + PKCE).",
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--client-secret", metavar="PATH")
    parser.add_argument("--auth-url", action="store_true")
    parser.add_argument("--auth-code", metavar="CODE_OR_URL")
    parser.add_argument("--services", default="all", help="comma list from: " + ", ".join(SERVICE_SCOPES) + ", all")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    as_json = args.format == "json"

    if args.check:
        return cmd_check(as_json)
    if args.client_secret:
        return cmd_client_secret(args.client_secret, as_json)
    if args.auth_url:
        return cmd_auth_url(args.services, as_json)
    if args.auth_code:
        return cmd_auth_code(args.auth_code, as_json)

    build_parser().print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
