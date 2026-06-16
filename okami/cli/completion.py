"""Shell-completion p/ bash/zsh/fish (#11, port do Hermes hermes_cli/completion.py).

Tab-completion zero-setup p/ subcomandos e flags. Como o app é Typer/Click, reaproveitamos o mecanismo
de completion do Click (env var `_OKAMI_COMPLETE=<shell>_source`) — robusto e sempre em dia com a árvore
de comandos, em vez de manter scripts à mão.
"""
from __future__ import annotations

_SHELLS = {
    "bash": '# Okami completion (bash) — adicione ao ~/.bashrc:\neval "$(_OKAMI_COMPLETE=bash_source okami)"\n',
    "zsh": '# Okami completion (zsh) — adicione ao ~/.zshrc:\neval "$(_OKAMI_COMPLETE=zsh_source okami)"\n',
    "fish": "# Okami completion (fish) — adicione ao ~/.config/fish/completions/okami.fish:\n"
            "_OKAMI_COMPLETE=fish_source okami | source\n",
}


def completion_script(shell: str) -> str | None:
    """Snippet de completion p/ `shell` (bash/zsh/fish), ou None se não suportado."""
    return _SHELLS.get((shell or "").strip().lower())


__all__ = ["completion_script"]
