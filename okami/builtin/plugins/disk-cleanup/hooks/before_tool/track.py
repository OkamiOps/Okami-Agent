#!/usr/bin/env python3
"""disk-cleanup · hook before_tool (TRACK): registra os arquivos EFÊMEROS que esta escrita vai criar
(temp/scratch/*.tmp…), p/ o hook after_task apagá-los no fim. NUNCA veta (sempre exit 0) — é só
observação; um cleanup jamais deve bloquear o trabalho. Auto-contido (stdlib + _diskclean_lib)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # raiz do plugin (p/ achar _diskclean_lib)
import _diskclean_lib as lib  # noqa: E402


def main() -> int:
    payload = lib.load_payload()
    tool = str(payload.get("tool") or "")
    args = payload.get("args") or {}
    if not isinstance(args, dict):
        return 0
    cwd = os.getcwd()
    eph = [p for p in lib.candidate_paths(tool, args, cwd) if lib.is_ephemeral(p, cwd)]
    if not eph:
        return 0
    state = lib.load_state()
    key = lib.project_key(cwd)
    cur = state.get(key) or []
    for p in eph:
        if p not in cur:
            cur.append(p)
    state[key] = cur
    lib.save_state(state)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:      # noqa: BLE001 — track nunca derruba/veta a tool
        sys.exit(0)
