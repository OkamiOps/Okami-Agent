"""Design-system da CLI do Okami — componentes visuais REUTILIZÁVEIS p/ todos os comandos.

O `okami chat` (TUI) tem a cara da marca; os comandos (`status`/`config`/`doctor`/`auth`/`tools`)
ficavam em Rich cru, cada um de um jeito. Aqui mora a identidade ÚNICA: paleta da marca, badges de
status, key-value alinhado, cards arredondados e tabelas limpas (sem grade pesada). Todo comando
compõe a partir DESTAS peças → consistência visual de ponta a ponta.
"""

from __future__ import annotations

import rich.box as _box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from okami.tui import CYAN, DIM, FG, MAGENTA, MUTE, ORANGE, SOFT, _grad_color  # paleta da marca

# semânticas (verde/âmbar/vermelho) fora da paleta de marca, p/ estado
GREEN = "#3fb950"
AMBER = "#ffb86c"
RED = "#ff5555"

__all__ = ["ORANGE", "CYAN", "MAGENTA", "FG", "SOFT", "MUTE", "DIM", "GREEN", "AMBER", "RED",
           "header", "section", "card", "kv", "kv_grid", "badge", "dot", "data_table", "hint", "gradient"]

# estado → (cor, símbolo). Cobre os status que os comandos usam (auth/doctor/policy/lint).
_STATE = {
    "ok": (GREEN, "●"), "ready": (GREEN, "●"), "on": (GREEN, "●"), "pass": (GREEN, "✓"),
    "yes": (GREEN, "✓"), "up": (GREEN, "●"),
    "warn": (AMBER, "▲"), "expired": (AMBER, "◐"), "partial": (AMBER, "◐"),
    "fail": (RED, "✗"), "missing": (RED, "○"), "off": (MUTE, "○"), "down": (RED, "✗"),
    "no": (MUTE, "—"), "none": (MUTE, "—"), "dim": (MUTE, "·"),
}


def gradient(text: str) -> Text:
    """Texto com o gradiente HORIZONTAL da marca (laranja→ciano→magenta) — p/ títulos/wordmark."""
    t = Text(no_wrap=True)
    n = max(1, len(text) - 1)
    for i, ch in enumerate(text):
        t.append(ch, style=f"bold {_grad_color(i / n)}")
    return t


def header(title: str, subtitle: str = "", *, icon: str = "🐺") -> Text:
    """Cabeçalho de comando: `🐺 OKAMI · título   subtítulo` (uma linha, com gradiente no wordmark)."""
    t = Text(no_wrap=True, overflow="ellipsis")
    t.append(f"{icon} ", style=ORANGE)
    t.append_text(gradient("OKAMI"))
    t.append("  ", style="")
    t.append(title, style=f"bold {FG}")
    if subtitle:
        t.append("   ", style="")
        t.append(subtitle, style=MUTE)
    return t


def section(title: str, *, icon: str = "", accent: str = ORANGE) -> Text:
    """Cabeçalho de seção: `▌ TÍTULO` (barra de acento + caixa-alta sutil)."""
    t = Text()
    t.append("▌ ", style=f"bold {accent}")
    if icon:
        t.append(f"{icon} ", style=accent)
    t.append(title.upper(), style=f"bold {SOFT}")
    return t


def dot(state: str) -> Text:
    """Só o símbolo colorido do estado (p/ usar inline numa célula)."""
    color, sym = _STATE.get(str(state).lower(), (MUTE, "·"))
    return Text(sym, style=f"bold {color}")


def badge(state: str, label: str = "") -> Text:
    """Pílula de estado: símbolo + rótulo colorido (ex.: ● ready / ✗ fail / ▲ warn)."""
    color, sym = _STATE.get(str(state).lower(), (MUTE, "·"))
    t = Text()
    t.append(f"{sym} ", style=f"bold {color}")
    t.append(label or str(state), style=color)
    return t


def kv_grid(rows, *, label_style: str = MUTE, value_style: str = FG, gutter: int = 2) -> Table:
    """Key-value ALINHADO (rótulo dim à direita, valor claro à esquerda). `rows`: [(k, v)], v pode ser Text."""
    g = Table.grid(padding=(0, gutter, 0, 0))
    g.add_column(justify="right", style=label_style, no_wrap=True)
    g.add_column(style=value_style, overflow="fold")
    for k, v in rows:
        g.add_row(k, v if isinstance(v, Text) else Text(str(v), style=value_style))
    return g


def kv(rows, **kw) -> Table:
    """Alias semântico p/ kv_grid."""
    return kv_grid(rows, **kw)


def card(body, *, title: str = "", subtitle: str = "", accent: str = ORANGE, pad=(1, 2)) -> Panel:
    """Card arredondado com borda dim e título em acento — o container padrão dos comandos."""
    return Panel(body, box=_box.ROUNDED, border_style=DIM, padding=pad,
                 title=(_title(title, accent) if title else None), title_align="left",
                 subtitle=(Text(subtitle, style=MUTE) if subtitle else None), subtitle_align="right")


def _title(title: str, accent: str) -> Text:
    t = Text()
    t.append("● ", style=accent)
    t.append(title, style=f"bold {accent}")
    return t


def data_table(*columns, title: str = "", accent: str = ORANGE) -> Table:
    """Tabela LIMPA (sem grade vertical pesada): header em acento + linha de base dim. `columns`:
    str OU (nome, {opções rich da coluna})."""
    t = Table(box=_box.SIMPLE_HEAD, show_edge=False, header_style=f"bold {accent}",
              border_style=DIM, pad_edge=False, padding=(0, 2, 0, 0),
              title=(Text(title, style=f"bold {accent}") if title else None), title_justify="left")
    for col in columns:
        if isinstance(col, tuple):
            name, opts = col
            t.add_column(name, **opts)
        else:
            t.add_column(col)
    return t


def hint(text: str) -> Text:
    """Linha de dica/rodapé discreta (`dim`), com setinha."""
    return Text(f"→ {text}", style=MUTE)


def stack(*renderables) -> Group:
    """Empilha renderables com uma linha em branco entre eles (respiro)."""
    out = []
    for i, r in enumerate(renderables):
        if i:
            out.append(Text(""))
        out.append(r)
    return Group(*out)
