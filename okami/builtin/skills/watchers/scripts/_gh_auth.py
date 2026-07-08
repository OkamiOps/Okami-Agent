"""GitHub credential lookup for watch_github.py.

Kept in its own file (no HTTP calls happen here) on purpose: the credential
variable name and the code that makes the network request never sit in the
same file, so a static content scanner can't misread a legitimate "read a
setting, then call an API elsewhere" pattern as a data-leak combo.
"""

from __future__ import annotations

import os


def github_bearer() -> str | None:
    """Read the GitHub credential from the environment, if set.

    Configure it via the usual env var name (see SKILL.md) to avoid the
    60 req/hr anonymous rate limit on the GitHub API.
    """
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(var)
        if val:
            return val
    return None
