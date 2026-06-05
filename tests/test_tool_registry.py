"""Registro declarativo de tools (#14): catálogo é a fonte única e NÃO drifta das tools reais."""

from __future__ import annotations

from okami.core.tool_registry import TOOL_REGISTRY, by_category, missing, spec
from okami.core.tools import default_registry


def test_every_registered_tool_has_metadata():
    """Anti-drift: nenhuma tool de runtime pode existir sem metadata no registry."""
    assert missing(list(default_registry())) == []


def test_no_orphan_specs():
    """E nenhuma metadata pode apontar p/ tool inexistente."""
    reg = set(default_registry())
    assert [s.name for s in TOOL_REGISTRY if s.name not in reg] == []


def test_terminal_flag_matches_real_tool():
    reg = default_registry()
    for s in TOOL_REGISTRY:
        assert s.terminal == reg[s.name].terminal, f"{s.name}: terminal diverge da tool real"


def test_by_category_orders_and_filters():
    cats = by_category()
    assert list(cats)[0] == "conversa"                          # ordem canônica (respond primeiro)
    assert any(s.name == "read_file" for s in cats["arquivo"])
    only = by_category({"run_shell"})                           # filtro por nomes
    assert list(only) == ["shell"] and only["shell"][0].name == "run_shell"


def test_danger_metadata_is_sane():
    assert spec("run_shell").danger == "dangerous"
    assert spec("write_file").danger == "sensitive"
    assert spec("read_file").danger == "safe"
