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


# ── skills NATIVAS (mesmo mecanismo: embarcadas no pacote, mergeadas no runner) ──
def test_builtin_skills_load_and_scan_clean():
    from okami.skills import load_builtin_skills
    from okami.skills.skill_security import scan_path
    bs = load_builtin_skills()
    names = {s.name for s in bs}
    assert {"criar-pull-request", "depuracao-sistematica", "pesquisa-web"} <= names
    for s in bs:
        assert not scan_path(s.path.parent).blocked       # nativas DEVEM passar limpo no scan (senão somem)


def test_with_builtin_user_skill_wins_on_name_clash():
    import dataclasses
    from okami.skills import load_builtin_skills, with_builtin
    bs = load_builtin_skills()
    clash = dataclasses.replace(bs[0], description="VERSÃO DO USUÁRIO")   # mesma `name`, descrição diferente
    merged = with_builtin([clash])
    same = [s for s in merged if s.name == bs[0].name]
    assert len(same) == 1 and same[0].description == "VERSÃO DO USUÁRIO"  # usuário vence
    assert len(merged) == len(bs)                          # sem duplicar a nativa de mesmo nome
