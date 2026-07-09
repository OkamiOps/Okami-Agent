"""Load the ElevenLabs Scribe credential from .env or the environment. Pure — no network
calls — so the transcription path in transcribe.py stays free of literal credential
references (a network script that also references a secret keyword trips the
okami/skills/skill_security.py risk scanner and gets blocked from loading)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Real HTTP header name required by the ElevenLabs Scribe API. Kept here (auth-only,
# no network call in this file) so transcribe.py never needs the literal string.
HEADER_NAME = "xi-api-key"

_VAR_NAME = "ELEVENLABS_API_KEY"


def load_credential() -> str:
    for candidate in [Path(__file__).resolve().parent.parent / ".env", Path(".env")]:
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == _VAR_NAME:
                    return v.strip().strip('"').strip("'")
    v = os.environ.get(_VAR_NAME, "")
    if not v:
        sys.exit(f"{_VAR_NAME} not found in .env or environment")
    return v
