"""Ecossistema de plugins (#12, port do Hermes hermes_cli/plugins.py).

Descobre plugins de 3 fontes (combináveis): pasta bundled/user/project (`<root>/plugins/<nome>/
plugin.yaml`) e entry-point pip (grupo `okami.plugins`). Cada plugin declara `hooks` (pre_llm_call,
post_tool_call, before_skill_install…) que o HookManager já roda. Estende `automation/hooks.py` com a
camada de DESCOBERTA — antes só config + pasta `hooks/`; agora também plugin instalável.

Fail-safe: plugin.yaml quebrado/ilegível é IGNORADO (não derruba o boot).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Plugin:
    name: str
    source: str                    # "folder" | "entry_point"
    hooks: list[str] = field(default_factory=list)
    path: str = ""
    value: str = ""                # p/ entry_point: "modulo:objeto"


def _from_folder(root) -> list[Plugin]:
    out: list[Plugin] = []
    base = Path(root) / "plugins"
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        manifest = d / "plugin.yaml"
        if not manifest.is_file():
            continue
        try:
            meta = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            if not isinstance(meta, dict):
                continue
        except (yaml.YAMLError, OSError):
            continue                # plugin quebrado → ignora
        name = str(meta.get("name") or d.name)
        hooks = [str(h) for h in (meta.get("hooks") or [])]
        out.append(Plugin(name=name, source="folder", hooks=hooks, path=str(d)))
    return out


def discover_plugins(roots, *, entry_points=None) -> list[Plugin]:
    """Plugins descobertos nas `roots` (pasta `<root>/plugins/`) + entry-points pip (grupo okami.plugins).
    `entry_points`: iterável com .name/.value (default: lê do ambiente). Dedup por nome (pasta vence)."""
    found: dict[str, Plugin] = {}
    for root in (roots or []):
        for p in _from_folder(root):
            found.setdefault(p.name, p)
    eps = entry_points
    if eps is None:
        try:
            from importlib import metadata
            eps = metadata.entry_points(group="okami.plugins")
        except Exception:  # noqa: BLE001
            eps = ()
    for ep in (eps or ()):
        name = getattr(ep, "name", "")
        if name and name not in found:
            found[name] = Plugin(name=name, source="entry_point", value=getattr(ep, "value", ""))
    return list(found.values())


def plugin_roots() -> list[Path]:
    """Raízes padrão: projeto (.) + home do Okami."""
    roots = [Path(".")]
    try:
        from okami.home import okami_home
        roots.append(okami_home())
    except Exception:  # noqa: BLE001
        pass
    return roots


__all__ = ["Plugin", "discover_plugins", "plugin_roots"]
