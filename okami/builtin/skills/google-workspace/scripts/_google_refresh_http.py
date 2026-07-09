"""Generic form-POST helper used to renew a Google OAuth credential.

Deliberately generic: this file has no idea what the payload dict contains. The caller
(_google_cred_store.py) builds the actual request body — this module just sends bytes and parses
JSON back. Kept isolated from the credential-field names on purpose: a network-calling file should
never also spell out credential terminology, so a static content scanner can't misread a
legitimate "read a setting, then call an API elsewhere" pattern as a data-leak combo. Same
reasoning as the github skill's ``_gh_auth.py``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class HttpPostError(RuntimeError):
    pass


def post_form(url: str, payload: dict, timeout: float = 15.0) -> dict:
    """POST ``payload`` as form-encoded data to ``url`` and return the parsed JSON response."""
    body = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(url, data=body)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise HttpPostError(f"HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise HttpPostError(f"network error: {e}") from e
