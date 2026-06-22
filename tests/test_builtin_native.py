"""Plugins (e skills) NATIVOS: embarcados no pacote okami/builtin/, descobertos independente do CWD —
uma instalação limpa (pip install) já vem com eles, sem o usuário pôr nada em ./plugins ou ~/.okami."""
from __future__ import annotations

import os
import tempfile


def test_builtin_plugins_root_exists_with_manifests():
    from okami.builtin import builtin_plugins_root
    root = builtin_plugins_root()
    assert root.is_dir()
    names = {p.name for p in root.iterdir() if (p / "plugin.yaml").is_file()}
    assert {"security-guidance", "disk-cleanup", "usage-observer"} <= names   # os 3 nativos viajam no pacote


def test_plugin_roots_includes_builtin():
    from okami.builtin import builtin_root
    from okami.plugins import plugin_roots
    assert builtin_root() in plugin_roots()                    # discover_plugins enxerga os nativos


def test_discover_plugins_finds_builtin_from_any_cwd():
    from okami.plugins import discover_plugins, plugin_roots
    cwd = os.getcwd()
    try:
        os.chdir(tempfile.mkdtemp())                           # CWD vazio (sem ./plugins) → ainda acha os nativos
        names = {p.name for p in discover_plugins(plugin_roots())}
        assert {"security-guidance", "disk-cleanup", "usage-observer"} <= names
    finally:
        os.chdir(cwd)


def test_hookmanager_fires_builtin_only_when_enabled(tmp_path):
    """include_builtin=False (default) NÃO descobre nativos (isolamento de teste); True descobre."""
    from okami.automation.hooks import HookManager
    off = HookManager(root=str(tmp_path), include_builtin=False)
    assert off._plugin_scripts("before_tool") == []            # root vazio + nativos OFF → nada
    on = HookManager(root=str(tmp_path), include_builtin=True)
    scripts = on._plugin_scripts("before_tool")
    assert any("security-guidance" in str(s) for s in scripts)  # nativo descoberto p/ execução
