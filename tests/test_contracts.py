"""Testes do verification gate de UI (§4.3)."""

from __future__ import annotations

from okami.contracts import check_ui

CONTRACT = {
    "component_source": "@/components/ui",
    "forbid_inline_hex": True,
    "forbid_raw_css": True,
    "require_component_source": True,
}


def test_gate_flags_ugly_ui(tmp_path):
    (tmp_path / "Bad.tsx").write_text(
        'export const B = () => (<div style={{color: "#ffffff"}}>'
        "<style>.x{color:red}</style>oi</div>)",
        encoding="utf-8",
    )
    rules = {v.rule for v in check_ui(tmp_path, CONTRACT)}
    assert {"no_inline_hex", "no_raw_style_tag", "no_inline_style", "require_component_source"} <= rules


def test_gate_passes_clean_shadcn(tmp_path):
    (tmp_path / "Good.tsx").write_text(
        'import { Button } from "@/components/ui/button"\n'
        "export const G = () => <Button>ok</Button>\n",
        encoding="utf-8",
    )
    assert check_ui(tmp_path, CONTRACT) == []


def test_gate_empty_dir_passes(tmp_path):
    assert check_ui(tmp_path, CONTRACT) == []
