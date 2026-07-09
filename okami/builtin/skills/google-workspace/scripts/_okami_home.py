"""Resolve OKAMI_HOME for standalone skill scripts.

Skill scripts run as plain ``python3 script.py`` outside the main Okami process, so they can't
import the main package's config module. This mirrors the same default other builtin skills use
(``$OKAMI_HOME``, falling back to ``~/.okami``) with stdlib only.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_okami_home() -> Path:
    val = os.environ.get("OKAMI_HOME", "").strip()
    return Path(val) if val else Path.home() / ".okami"


def display_okami_home() -> str:
    home = get_okami_home()
    try:
        return "~/" + str(home.relative_to(Path.home()))
    except ValueError:
        return str(home)
