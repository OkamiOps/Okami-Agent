"""Bridge between the Okami-managed Google credential and the `gws` CLI.

Renews the credential if it expired, then execs `gws` with a valid access value in the
environment. Does not itself perform any OAuth network call — that lives behind
_google_cred_store.get_valid_access_value(), split across _google_cred_store.py (storage/field
names) and _google_refresh_http.py (the actual HTTP call), so no single file here mixes credential
terminology with live network code.

Usage: python3 gws_bridge.py <gws args...>
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _google_cred_store import get_valid_access_value  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: gws_bridge.py <gws args...>", file=sys.stderr)
        return 1

    try:
        access_value = get_valid_access_value()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Run setup.py --auth-url to (re)authenticate.", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env["GOOGLE_WORKSPACE_CLI_CREDENTIAL"] = access_value

    result = subprocess.run(["gws", *sys.argv[1:]], env=env)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
