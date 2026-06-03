"""Menus interativos (§13) — seleção por seta ↑↓ (estilo Hermes), com fallback numerado.

Centraliza TODA a interação de config (setup, provider add, etc.) numa API só, pra nenhuma
configuração precisar de edição manual de YAML. Usa `questionary` (prompt_toolkit) quando há TTY;
sem TTY (CI, pipe, testes) cai pra um prompt numerado via Rich+typer. Nunca quebra."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Sequence

from rich.console import Console

_console = Console()


@dataclass
class Choice:
    value: str
    label: str
    hint: str = ""           # descrição curta à direita
    active: bool = False     # valor atual ("← currently active")


def _interactive() -> bool:
    """questionary disponível E stdin/stdout são um terminal real."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        import questionary  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _qstyle():
    from questionary import Style
    return Style([                       # paleta da marca Okami (Heat Orange / Volt Cyan / Bone)
        ("qmark", "fg:#ff7527 bold"), ("question", "fg:#f4f4f8 bold"),
        ("pointer", "fg:#ff7527 bold"), ("highlighted", "fg:#00dfe8 bold"),
        ("selected", "fg:#00dfe8"), ("answer", "fg:#ff7527 bold"),
        ("instruction", "fg:#6c6d80"), ("disabled", "fg:#3d3e50"),
    ])


def _norm(choices: Sequence) -> list[Choice]:
    out = []
    for c in choices:
        if isinstance(c, Choice):
            out.append(c)
        elif isinstance(c, (tuple, list)):
            value, label = c[0], c[1]
            hint = c[2] if len(c) > 2 else ""
            out.append(Choice(value, label, hint))
        else:
            out.append(Choice(str(c), str(c)))
    return out


def select(title: str, choices: Sequence, *, default: str | None = None) -> str | None:
    """Escolhe UM item. `choices`: Choice | (value,label[,hint]). Devolve value (ou None se cancelar)."""
    items = _norm(choices)
    for it in items:                         # marca o ativo (default ganha prioridade)
        it.active = it.active or (default is not None and it.value == default)
    active = next((it.value for it in items if it.active), default)

    if _interactive():
        import questionary
        qs = []
        for it in items:
            txt = it.label + (f"  — {it.hint}" if it.hint else "") + ("  ← atual" if it.active else "")
            qs.append(questionary.Choice(title=txt, value=it.value))
        ans = questionary.select(title, choices=qs, default=active, style=_qstyle(),
                                 qmark="◆", instruction="(↑↓ navega · Enter escolhe · Esc cancela)").ask()
        return ans

    # fallback numerado (sem TTY)
    _console.print(f"[bold #ffd166]{title}[/]")
    default_idx = 1
    for i, it in enumerate(items, 1):
        mark = " [green]← atual[/green]" if it.active else ""
        hint = f" [dim]— {it.hint}[/dim]" if it.hint else ""
        _console.print(f"  [bold]{i:>2}[/bold]. {it.label}{hint}{mark}")
        if it.active:
            default_idx = i
    import typer
    try:
        sel = typer.prompt(f"Escolha [1-{len(items)}]", default=str(default_idx))
    except Exception:  # noqa: BLE001 — não-interativo de verdade → usa o ativo/1º
        return active or (items[0].value if items else None)
    try:
        return items[int(str(sel).strip()) - 1].value
    except (ValueError, IndexError):
        return active or (items[0].value if items else None)


def text(message: str, *, default: str = "", password: bool = False) -> str:
    """Campo de texto (uma linha). password=True esconde a digitação (chaves/tokens)."""
    if _interactive():
        import questionary
        fn = questionary.password if password else questionary.text
        return (fn(message, default=("" if password else default), style=_qstyle()).ask() or default)
    import typer
    try:
        return typer.prompt(message, default=default, hide_input=password)
    except Exception:  # noqa: BLE001
        return default


def confirm(message: str, *, default: bool = False) -> bool:
    """Sim/não."""
    if _interactive():
        import questionary
        ans = questionary.confirm(message, default=default, style=_qstyle()).ask()
        return bool(default if ans is None else ans)
    import typer
    try:
        return typer.confirm(message, default=default)
    except Exception:  # noqa: BLE001
        return default


def checkbox(title: str, choices: Sequence, *, preselected: Sequence[str] = ()) -> list[str]:
    """Multi-seleção (espaço marca, Enter confirma). Fallback: csv de números."""
    items = _norm(choices)
    pre = set(preselected)
    if _interactive():
        import questionary
        qs = [questionary.Choice(title=(it.label + (f"  — {it.hint}" if it.hint else "")),
                                 value=it.value, checked=it.value in pre) for it in items]
        return questionary.checkbox(title, choices=qs, style=_qstyle()).ask() or []
    _console.print(f"[bold #ffd166]{title}[/] [dim](números separados por vírgula)[/dim]")
    for i, it in enumerate(items, 1):
        _console.print(f"  [bold]{i:>2}[/bold]. {it.label}" + (" [green]✓[/green]" if it.value in pre else ""))
    import typer
    try:
        raw = typer.prompt("Marque", default="")
    except Exception:  # noqa: BLE001
        return list(pre)
    picked = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok.isdigit() and 1 <= int(tok) <= len(items):
            picked.append(items[int(tok) - 1].value)
    return picked or list(pre)
