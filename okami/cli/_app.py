from __future__ import annotations

import sys

import typer
from rich.console import Console

app = typer.Typer(add_completion=False, help="Okami Agent — CLI")

# UTF-8 consistente em qualquer SO (acentos/§ no console Windows; no-op em Linux/macOS).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

console = Console()
