"""CLI do Okami — pacote. `app` é o entrypoint Typer; os submódulos registram os comandos."""
from __future__ import annotations

from okami.cli._app import app, console  # noqa: F401

# Importa os módulos de comando p/ registrar @app.command / add_typer (ordem = ordem no --help).
from okami.cli.commands import (  # noqa: F401,E402
    basics, task, skills, memory, setup, persona, cron,
    chat, media, gateway, provider, config, misc,
    auth, policy, observability, readiness, curator, channel, fsaccess, sendmsg,
)

# Re-exports p/ compatibilidade (testes e o gateway importam de okami.cli):
from okami.cli._shared import (  # noqa: F401,E402
    _load, _set_env_var, _build_memory_block, _detect_environment, _Detected,
)
from okami.cli.commands.config import _coerce, _is_secret_key, _redact  # noqa: F401,E402
from okami.cli.commands.chat import _route_repl_line  # noqa: F401,E402

__all__ = ["app", "console"]
