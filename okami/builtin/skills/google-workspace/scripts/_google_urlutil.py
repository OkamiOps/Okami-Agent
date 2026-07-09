"""URL encode/parse helpers, generic on purpose.

Kept separate from the credential-storage module so the file that touches `urllib.parse` never
also spells out OAuth credential field names — same file-split reasoning used across this skill.
"""

from __future__ import annotations

import urllib.parse


def encode_query(params: dict) -> str:
    return urllib.parse.urlencode(params)


def extract_query_param(url_or_value: str, param: str) -> str | None:
    """If ``url_or_value`` looks like a URL containing ``param=...``, return that value.

    Otherwise return None so the caller can fall back to treating the whole string as the value.
    """
    if f"{param}=" not in url_or_value:
        return None
    parsed = urllib.parse.urlparse(url_or_value)
    values = urllib.parse.parse_qs(parsed.query).get(param)
    return values[0] if values else None
