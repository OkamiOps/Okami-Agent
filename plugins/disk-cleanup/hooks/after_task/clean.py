#!/usr/bin/env python3
"""disk-cleanup · hook after_task (CLEAN): apaga os efêmeros rastreados DESTE projeto e zera o estado.
SEGURANÇA em profundidade: só apaga arquivo REGULAR que (1) ainda existe, (2) NÃO é symlink, (3) ainda
classifica como efêmero. Mexe só nas entradas cujo projeto == cwd atual (não toca outros projetos)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import _diskclean_lib as lib  # noqa: E402


def main() -> int:
    cwd = os.getcwd()
    cwd_real = lib.project_key(cwd)
    state = lib.load_state()
    removed = 0
    for key in list(state):
        if lib.project_key(key) != cwd_real:
            continue                                   # outro projeto → não toca
        for path in state.get(key) or []:
            p = Path(path)
            try:
                if p.is_symlink() or not p.exists() or not p.is_file():
                    continue                           # symlink/inexistente/dir → pula (segurança)
                if not lib.is_ephemeral(str(p), cwd):
                    continue                           # deixou de ser efêmero → não apaga
                p.unlink()
                removed += 1
            except OSError:
                continue
        state.pop(key, None)                           # zera o registro deste projeto
    lib.save_state(state)
    if removed:
        print(f"disk-cleanup: {removed} arquivo(s) efêmero(s) removido(s) no fim da tarefa")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:      # noqa: BLE001 — after_task é observador; erro não derruba o agente
        sys.exit(0)
