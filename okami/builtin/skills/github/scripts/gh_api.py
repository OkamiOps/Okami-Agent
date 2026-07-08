"""GitHub REST API fallback for when the `gh` CLI isn't installed.

Stdlib only. Covers the operations SKILL.md documents as "gh-first, this
script as the git+curl-equivalent fallback": CI/check status, PR merge,
and basic issue management. Credential lookup lives in _gh_auth.py (kept
separate from this file's network calls — see that module's docstring).

Usage:
    python3 gh_api.py ci-status --owner OWNER --repo REPO --sha SHA
    python3 gh_api.py pr-list --owner OWNER --repo REPO [--state open]
    python3 gh_api.py pr-merge --owner OWNER --repo REPO --number N [--method squash]
    python3 gh_api.py issue-create --owner OWNER --repo REPO --title T [--body B]
    python3 gh_api.py issue-list --owner OWNER --repo REPO [--state open]
    python3 gh_api.py issue-comment --owner OWNER --repo REPO --number N --body B
    python3 gh_api.py issue-close --owner OWNER --repo REPO --number N

--owner/--repo default to the `origin` git remote of the current directory
when omitted (parsed the same way the SKILL.md's OWNER/REPO snippet does).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _gh_auth import github_bearer  # type: ignore

API = "https://api.github.com"


def _owner_repo_from_remote() -> tuple[str, str]:
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"gh_api: couldn't read git remote and --owner/--repo not given: {e}")
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)(?:\.git)?$", out)
    if not m:
        raise SystemExit(f"gh_api: couldn't parse owner/repo from remote {out!r}")
    return m.group(1), m.group(2)


def _request(method: str, path: str, *, body: dict | None = None) -> tuple[int, object]:
    url = f"{API}{path}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Okami-gh-api/1.0"}
    bearer = github_bearer()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw.decode("utf-8", errors="replace")


def cmd_ci_status(a) -> int:
    status_code, data = _request("GET", f"/repos/{a.owner}/{a.repo}/commits/{a.sha}/check-runs")
    if status_code >= 300:
        print(json.dumps({"error": data, "http_status": status_code}, indent=2))
        return 1
    runs = (data or {}).get("check_runs", []) if isinstance(data, dict) else []
    out = [{"name": r.get("name"), "status": r.get("status"), "conclusion": r.get("conclusion")}
           for r in runs]
    print(json.dumps({"check_runs": out}, indent=2))
    return 0


def cmd_pr_list(a) -> int:
    status_code, data = _request("GET", f"/repos/{a.owner}/{a.repo}/pulls?state={a.state}")
    if status_code >= 300:
        print(json.dumps({"error": data, "http_status": status_code}, indent=2))
        return 1
    out = [{"number": p.get("number"), "title": p.get("title"), "author": (p.get("user") or {}).get("login")}
           for p in (data or [])]
    print(json.dumps(out, indent=2))
    return 0


def cmd_pr_merge(a) -> int:
    body = {"merge_method": a.method}
    status_code, data = _request("PUT", f"/repos/{a.owner}/{a.repo}/pulls/{a.number}/merge", body=body)
    print(json.dumps({"http_status": status_code, "response": data}, indent=2))
    return 0 if status_code < 300 else 1


def cmd_issue_create(a) -> int:
    body = {"title": a.title, "body": a.body or ""}
    status_code, data = _request("POST", f"/repos/{a.owner}/{a.repo}/issues", body=body)
    print(json.dumps({"http_status": status_code, "response": data}, indent=2))
    return 0 if status_code < 300 else 1


def cmd_issue_list(a) -> int:
    status_code, data = _request("GET", f"/repos/{a.owner}/{a.repo}/issues?state={a.state}")
    if status_code >= 300:
        print(json.dumps({"error": data, "http_status": status_code}, indent=2))
        return 1
    out = [{"number": i.get("number"), "title": i.get("title"), "state": i.get("state")}
           for i in (data or []) if "pull_request" not in i]
    print(json.dumps(out, indent=2))
    return 0


def cmd_issue_comment(a) -> int:
    body = {"body": a.body}
    status_code, data = _request("POST", f"/repos/{a.owner}/{a.repo}/issues/{a.number}/comments", body=body)
    print(json.dumps({"http_status": status_code, "response": data}, indent=2))
    return 0 if status_code < 300 else 1


def cmd_issue_close(a) -> int:
    body = {"state": "closed"}
    status_code, data = _request("PATCH", f"/repos/{a.owner}/{a.repo}/issues/{a.number}", body=body)
    print(json.dumps({"http_status": status_code, "response": data}, indent=2))
    return 0 if status_code < 300 else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def _common(sp):
        sp.add_argument("--owner", default="")
        sp.add_argument("--repo", default="")

    s = sub.add_parser("ci-status"); _common(s); s.add_argument("--sha", required=True)
    s = sub.add_parser("pr-list"); _common(s); s.add_argument("--state", default="open")
    s = sub.add_parser("pr-merge"); _common(s)
    s.add_argument("--number", required=True, type=int)
    s.add_argument("--method", default="squash", choices=["merge", "squash", "rebase"])
    s = sub.add_parser("issue-create"); _common(s)
    s.add_argument("--title", required=True); s.add_argument("--body", default="")
    s = sub.add_parser("issue-list"); _common(s); s.add_argument("--state", default="open")
    s = sub.add_parser("issue-comment"); _common(s)
    s.add_argument("--number", required=True, type=int); s.add_argument("--body", required=True)
    s = sub.add_parser("issue-close"); _common(s); s.add_argument("--number", required=True, type=int)

    return p


def main() -> int:
    a = build_parser().parse_args()
    if not a.owner or not a.repo:
        a.owner, a.repo = _owner_repo_from_remote()

    handlers = {
        "ci-status": cmd_ci_status,
        "pr-list": cmd_pr_list,
        "pr-merge": cmd_pr_merge,
        "issue-create": cmd_issue_create,
        "issue-list": cmd_issue_list,
        "issue-comment": cmd_issue_comment,
        "issue-close": cmd_issue_close,
    }
    return handlers[a.command](a)


if __name__ == "__main__":
    raise SystemExit(main())
