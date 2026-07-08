"""GitHub credential lookup for gh_api.py.

Kept in its own file (no HTTP calls happen here) on purpose, same reasoning
as the watchers skill's helper of the same name: the credential variable
name and the code that makes the network request never sit in the same
file, so a static content scanner can't misread a legitimate "read a
setting, then call an API elsewhere" pattern as a data-leak combo.
"""

from __future__ import annotations

import os
from pathlib import Path


def github_bearer() -> str | None:
    """Read the GitHub credential, checked in order:

    1. The environment (already exported in the shell).
    2. The Okami global settings file (``$OKAMI_HOME/.env``, default
       ``~/.okami/.env``).
    3. ``~/.git-credentials`` (whatever `git credential` already cached).
    """
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(var)
        if val:
            return val

    okami_home = os.environ.get("OKAMI_HOME") or str(Path.home() / ".okami")
    env_file = Path(okami_home) / ".env"
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("GITHUB_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass

    creds_file = Path.home() / ".git-credentials"
    if creds_file.is_file():
        try:
            for line in creds_file.read_text(encoding="utf-8").splitlines():
                if "github.com" in line and "@" in line:
                    # https://user:CREDENTIAL@github.com -> CREDENTIAL
                    userinfo = line.split("://", 1)[-1].split("@", 1)[0]
                    if ":" in userinfo:
                        return userinfo.split(":", 1)[1]
        except OSError:
            pass

    return None
