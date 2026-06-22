"""Recursos NATIVOS embarcados no pacote (viajam no `pip install`): plugins + skills built-in.

Resolvidos pelo caminho do próprio pacote (não pelo CWD), então uma instalação limpa já vem com eles —
diferente de `./plugins` e `~/.okami/plugins`, que dependem de o usuário ter posto algo lá. O agente
continua podendo CRIAR plugins/skills próprios (esses convivem; o do projeto vence o nativo de mesmo nome).
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent


def builtin_root() -> Path:
    return _HERE


def builtin_plugins_root() -> Path:
    """Plugins nativos: okami/builtin/plugins/<nome>/plugin.yaml + hooks/<evento>/*."""
    return _HERE / "plugins"


def builtin_skills_root() -> Path:
    """Skills nativas: okami/builtin/skills/<nome>/SKILL.md."""
    return _HERE / "skills"


__all__ = ["builtin_root", "builtin_plugins_root", "builtin_skills_root"]
