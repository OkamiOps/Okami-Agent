"""Contracts + Verification Gates (§4) — o anti-frontend-feio.

Gate mecânico que torna o design system LEI verificável: barra cor hex inline,
`<style>` cru, `style={{...}}` inline, e exige import da lib declarada (ShadCN/HeroUI).
É o gate HARD; o gosto de design (§9) entra depois como crítico soft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

UI_EXT = (".tsx", ".jsx", ".ts", ".js")
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_STYLE_TAG = re.compile(r"<style[\s>]")
_INLINE_STYLE = re.compile(r"style=\{\{")
_SKIP_DIRS = {"node_modules", ".git", ".next", "dist", "build", ".venv"}


@dataclass
class Violation:
    file: str
    line: int
    rule: str
    msg: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line} [{self.rule}] {self.msg}"


def _iter_ui_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in UI_EXT and not (_SKIP_DIRS & set(p.parts)):
            yield p


def check_ui(root: Path, contract: dict) -> list[Violation]:
    """Roda o gate de UI sobre `root`. Lista vazia = passou."""
    src = contract.get("component_source")
    forbid_hex = contract.get("forbid_inline_hex", True)
    forbid_css = contract.get("forbid_raw_css", True)
    require_src = contract.get("require_component_source", bool(src))

    violations: list[Violation] = []
    found_src_import = False
    files = list(_iter_ui_files(root))

    for p in files:
        rel = str(p.relative_to(root))
        text = p.read_text(encoding="utf-8", errors="ignore")
        if src and src in text:
            found_src_import = True
        for i, line in enumerate(text.splitlines(), 1):
            if forbid_hex and _HEX.search(line):
                violations.append(Violation(rel, i, "no_inline_hex",
                                            "cor hex inline — use tokens do tema"))
            if forbid_css and _STYLE_TAG.search(line):
                violations.append(Violation(rel, i, "no_raw_style_tag",
                                            "<style> cru — use o design system"))
            if forbid_css and _INLINE_STYLE.search(line):
                violations.append(Violation(rel, i, "no_inline_style",
                                            "style={{...}} inline — use componentes/classes do DS"))

    if require_src and src and files and not found_src_import:
        violations.append(Violation("(workspace)", 0, "require_component_source",
                                    f"nenhum import de '{src}' — use os componentes da lib"))
    return violations
