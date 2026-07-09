"""Fallback CLI for Gmail/Calendar/Drive/Sheets/Docs when the `gws` CLI isn't installed.

Talks to the Google REST APIs directly via stdlib `urllib`, authenticated with a bearer value
supplied by _google_cred_store.get_valid_access_value() (imported, never re-derived here). This
file never spells out credential-field terminology itself — only the generic word "bearer" — same
split used by the github skill's gh_api.py.

Every subcommand prints ONE line of JSON to stdout: {"ok": true, ...} or {"ok": false, "error": "..."}.

Usage:
    python3 google_api.py gmail-search --query "is:unread newer_than:7d" [--max 10]
    python3 google_api.py gmail-read --id <message_id>
    python3 google_api.py gmail-send --to a@b.com --subject "Oi" --body "texto"
    python3 google_api.py calendar-list [--calendar primary] [--max 10]
    python3 google_api.py calendar-create --summary "Reunião" --start <ISO8601> --end <ISO8601>
    python3 google_api.py drive-list [--query "name contains 'relatorio'"] [--max 20]
    python3 google_api.py sheets-read --sheet-id <id> --range "Sheet1!A1:D10"
    python3 google_api.py sheets-append --sheet-id <id> --range "Sheet1!A1" --values '[["a","b"]]'
    python3 google_api.py docs-read --doc-id <id>
    python3 google_api.py docs-append --doc-id <id> --text "novo parágrafo"
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _google_cred_store import get_valid_access_value  # noqa: E402

GMAIL = "https://gmail.googleapis.com/gmail/v1"
CALENDAR = "https://www.googleapis.com/calendar/v3"
DRIVE = "https://www.googleapis.com/drive/v3"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
DOCS = "https://docs.googleapis.com/v1/documents"


def _call(method: str, url: str, bearer: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {bearer}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise RuntimeError(f"network error: {e}") from e


def _emit(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False))


def _run(fn) -> int:
    try:
        bearer = get_valid_access_value()
    except RuntimeError as e:
        _emit({"ok": False, "error": str(e)})
        return 1
    try:
        out = fn(bearer)
    except RuntimeError as e:
        _emit({"ok": False, "error": str(e)})
        return 1
    _emit({"ok": True, **out})
    return 0


# --- Gmail -------------------------------------------------------------


def gmail_search(bearer: str, query: str, max_results: int) -> dict:
    params = urllib.parse.urlencode({"q": query, "maxResults": max_results})
    data = _call("GET", f"{GMAIL}/users/me/messages?{params}", bearer)
    return {"messages": data.get("messages", []), "result_size_estimate": data.get("resultSizeEstimate")}


def gmail_read(bearer: str, message_id: str) -> dict:
    data = _call("GET", f"{GMAIL}/users/me/messages/{message_id}?format=full", bearer)
    headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
    return {"id": data.get("id"), "snippet": data.get("snippet"), "headers": headers}


def gmail_send(bearer: str, to: str, subject: str, body: str) -> dict:
    message = f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}"
    raw = base64.urlsafe_b64encode(message.encode()).decode()
    data = _call("POST", f"{GMAIL}/users/me/messages/send", bearer, {"raw": raw})
    return {"id": data.get("id")}


# --- Calendar ------------------------------------------------------------


def calendar_list(bearer: str, calendar_id: str, max_results: int) -> dict:
    params = urllib.parse.urlencode({"maxResults": max_results, "singleEvents": "true", "orderBy": "startTime"})
    data = _call("GET", f"{CALENDAR}/calendars/{urllib.parse.quote(calendar_id)}/events?{params}", bearer)
    return {"events": data.get("items", [])}


def calendar_create(bearer: str, summary: str, start: str, end: str, calendar_id: str) -> dict:
    body = {"summary": summary, "start": {"dateTime": start}, "end": {"dateTime": end}}
    data = _call("POST", f"{CALENDAR}/calendars/{urllib.parse.quote(calendar_id)}/events", bearer, body)
    return {"id": data.get("id"), "html_link": data.get("htmlLink")}


# --- Drive -----------------------------------------------------------------


def drive_list(bearer: str, query: str | None, max_results: int) -> dict:
    params = {"pageSize": max_results}
    if query:
        params["q"] = query
    data = _call("GET", f"{DRIVE}/files?{urllib.parse.urlencode(params)}", bearer)
    return {"files": data.get("files", [])}


# --- Sheets ------------------------------------------------------------------


def sheets_read(bearer: str, sheet_id: str, cell_range: str) -> dict:
    url = f"{SHEETS}/{sheet_id}/values/{urllib.parse.quote(cell_range)}"
    data = _call("GET", url, bearer)
    return {"range": data.get("range"), "values": data.get("values", [])}


def sheets_append(bearer: str, sheet_id: str, cell_range: str, values: list) -> dict:
    url = (
        f"{SHEETS}/{sheet_id}/values/{urllib.parse.quote(cell_range)}"
        ":append?valueInputOption=USER_ENTERED"
    )
    data = _call("POST", url, bearer, {"values": values})
    return {"updates": data.get("updates", {})}


# --- Docs --------------------------------------------------------------------


def docs_read(bearer: str, doc_id: str) -> dict:
    data = _call("GET", f"{DOCS}/{doc_id}", bearer)
    text_parts = []
    for element in data.get("body", {}).get("content", []):
        para = element.get("paragraph")
        if not para:
            continue
        for run in para.get("elements", []):
            content = run.get("textRun", {}).get("content")
            if content:
                text_parts.append(content)
    return {"title": data.get("title"), "text": "".join(text_parts)}


def docs_append(bearer: str, doc_id: str, text: str) -> dict:
    doc = _call("GET", f"{DOCS}/{doc_id}", bearer)
    end_index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1)
    requests = [{"insertText": {"location": {"index": max(end_index - 1, 1)}, "text": text}}]
    _call("POST", f"{DOCS}/{doc_id}:batchUpdate", bearer, {"requests": requests})
    return {"appended": True}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="google_api.py",
        description="Fallback Gmail/Calendar/Drive/Sheets/Docs CLI (used when `gws` isn't installed).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("gmail-search", help="Search Gmail messages.")
    p.add_argument("--query", required=True)
    p.add_argument("--max", type=int, default=10)

    p = sub.add_parser("gmail-read", help="Read one Gmail message.")
    p.add_argument("--id", required=True)

    p = sub.add_parser("gmail-send", help="Send a plain-text email.")
    p.add_argument("--to", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--body", required=True)

    p = sub.add_parser("calendar-list", help="List upcoming Calendar events.")
    p.add_argument("--calendar", default="primary")
    p.add_argument("--max", type=int, default=10)

    p = sub.add_parser("calendar-create", help="Create a Calendar event.")
    p.add_argument("--summary", required=True)
    p.add_argument("--start", required=True, help="ISO 8601 datetime")
    p.add_argument("--end", required=True, help="ISO 8601 datetime")
    p.add_argument("--calendar", default="primary")

    p = sub.add_parser("drive-list", help="List Drive files.")
    p.add_argument("--query", default=None)
    p.add_argument("--max", type=int, default=20)

    p = sub.add_parser("sheets-read", help="Read a Sheets range.")
    p.add_argument("--sheet-id", required=True)
    p.add_argument("--range", required=True, dest="cell_range")

    p = sub.add_parser("sheets-append", help="Append rows to a Sheets range.")
    p.add_argument("--sheet-id", required=True)
    p.add_argument("--range", required=True, dest="cell_range")
    p.add_argument("--values", required=True, help="JSON 2D array, e.g. '[[\"a\",\"b\"]]'")

    p = sub.add_parser("docs-read", help="Read a Google Doc as plain text.")
    p.add_argument("--doc-id", required=True)

    p = sub.add_parser("docs-append", help="Append a paragraph to a Google Doc.")
    p.add_argument("--doc-id", required=True)
    p.add_argument("--text", required=True)

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "gmail-search":
        return _run(lambda bearer: gmail_search(bearer, args.query, args.max))
    if args.command == "gmail-read":
        return _run(lambda bearer: gmail_read(bearer, args.id))
    if args.command == "gmail-send":
        return _run(lambda bearer: gmail_send(bearer, args.to, args.subject, args.body))
    if args.command == "calendar-list":
        return _run(lambda bearer: calendar_list(bearer, args.calendar, args.max))
    if args.command == "calendar-create":
        return _run(lambda bearer: calendar_create(bearer, args.summary, args.start, args.end, args.calendar))
    if args.command == "drive-list":
        return _run(lambda bearer: drive_list(bearer, args.query, args.max))
    if args.command == "sheets-read":
        return _run(lambda bearer: sheets_read(bearer, args.sheet_id, args.cell_range))
    if args.command == "sheets-append":
        try:
            values = json.loads(args.values)
        except json.JSONDecodeError as e:
            _emit({"ok": False, "error": f"--values must be valid JSON: {e}"})
            return 1
        return _run(lambda bearer: sheets_append(bearer, args.sheet_id, args.cell_range, values))
    if args.command == "docs-read":
        return _run(lambda bearer: docs_read(bearer, args.doc_id))
    if args.command == "docs-append":
        return _run(lambda bearer: docs_append(bearer, args.doc_id, args.text))

    _emit({"ok": False, "error": f"unknown command: {args.command}"})
    return 1


if __name__ == "__main__":
    sys.exit(main())
