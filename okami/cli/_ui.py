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
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from okami.tui import CYAN, DIM, FG, MAGENTA, MUTE, ORANGE, SOFT, TAGLINE, _grad_color  # paleta da marca

# semânticas (verde/âmbar/vermelho) fora da paleta de marca, p/ estado
GREEN = "#3fb950"
AMBER = "#ffb86c"
RED = "#ff5555"

__all__ = ["ORANGE", "CYAN", "MAGENTA", "FG", "SOFT", "MUTE", "DIM", "GREEN", "AMBER", "RED",
           "header", "banner", "masthead", "section", "rule", "fields", "footer", "card", "panel",
           "grid", "meter", "meter_rows", "kv", "kv_grid", "badge", "dot", "data_table", "hint",
           "gradient", "stack"]

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


def banner(version: str = "", tagline: str = "IA com soberania para PMEs", *, icon: str = "🐺") -> Text:
    """Linha-banner do topo: `🐺 OKAMI v0.0.1 — IA com soberania para PMEs` (wordmark em gradiente)."""
    t = Text(no_wrap=True, overflow="ellipsis")
    t.append(f"{icon} ", style=ORANGE)
    t.append_text(gradient("OKAMI"))
    if version:
        t.append(f"  v{version}", style=MUTE)
    t.append(f"   —   {tagline}", style=ORANGE)
    return t


def masthead(version: str = "", *, tagline: str = "", right: str = "", icon: str = "🐺") -> Panel:
    """Barra-título EMOLDURADA (largura cheia): 🐺 + wordmark OKAMI espaçado em gradiente + versão à
    esquerda; tagline/estado à direita. É o topo dos painéis (status/doctor/config) — dá moldura à página."""
    left = Text(no_wrap=True, overflow="ellipsis")
    left.append(f"{icon}  ", style=ORANGE)
    left.append_text(gradient("OKAMI"))
    if version:
        left.append(f"   v{version}", style=MUTE)
    rt = Text(right or tagline or TAGLINE, no_wrap=True, overflow="ellipsis",
              style=SOFT if right else ORANGE, justify="right")
    bar = Table.grid(expand=True)
    bar.add_column(justify="left", ratio=3)
    bar.add_column(justify="right", ratio=2)
    bar.add_row(left, rt)
    return Panel(bar, box=_box.ROUNDED, border_style=ORANGE, padding=(0, 2))


def section(title: str, *, accent: str = CYAN) -> Text:
    """Cabeçalho de seção estilo Hermes/OpenClaw: `◆ Título` (diamante de acento)."""
    t = Text()
    t.append("◆ ", style=f"bold {accent}")
    t.append(title, style=f"bold {accent}")
    return t


def rule(title: str = "", *, accent: str = DIM) -> Rule:
    """Régua horizontal fina (com título opcional em acento) — separa blocos sem o peso de um card."""
    if title:
        return Rule(Text(title, style=f"bold {accent}"), style=accent, align="left")
    return Rule(style=accent)


def fields(rows, *, indent: int = 2, label_w: int = 0, label_style: str = MUTE, value_style: str = FG) -> Table:
    """Key-value FLAT estilo Hermes: `  Label   value` (rótulo à esquerda, sem caixa). v pode ser Text."""
    g = Table.grid(padding=(0, 2, 0, 0))
    g.add_column(justify="left", style=label_style, no_wrap=True, min_width=label_w)
    g.add_column(style=value_style, overflow="fold")
    pad = " " * indent
    for k, v in rows:
        g.add_row(pad + k, v if isinstance(v, Text) else Text(str(v), style=value_style))
    return g


def footer(title: str, items) -> Group:
    """Rodapé de próximos passos: `título:` + linhas `  comando   — descrição`."""
    out = [Text(title, style=f"bold {MUTE}")]
    for cmd, desc in items:
        line = Text("  ")
        line.append(cmd, style=CYAN)
        if desc:
            line.append(f"   {desc}", style=DIM)
        out.append(line)
    return Group(*out)


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


def card(body, *, title: str = "", subtitle: str = "", accent: str = ORANGE, pad=(1, 2),
         border: str = "") -> Panel:
    """Card arredondado com borda dim e título em acento — o container padrão dos comandos.
    `border` força a cor da borda (default = DIM discreto; passe um acento p/ destacar o card)."""
    return Panel(body, box=_box.ROUNDED, border_style=(border or DIM), padding=pad,
                 title=(_title(title, accent) if title else None), title_align="left",
                 subtitle=(Text(subtitle, style=MUTE) if subtitle else None), subtitle_align="right")


def panel(body, *, title: str = "", subtitle: str = "", accent: str = CYAN, pad=(1, 2)) -> Panel:
    """Card de SEÇÃO do dashboard: título `◆ Título` no acento + borda no MESMO acento (suave).
    É a peça que vai na grade de colunas — dá a cada bloco uma moldura clara, sem virar texto solto."""
    head = Text()
    head.append("◆ ", style=f"bold {accent}")
    head.append(title, style=f"bold {accent}")
    return Panel(body, box=_box.ROUNDED, border_style=accent, padding=pad,
                 title=head if title else None, title_align="left",
                 subtitle=(Text(subtitle, style=MUTE) if subtitle else None), subtitle_align="right")


def grid(cards, *, cols: int = 2, width: int = 0, gutter: int = 1):
    """Arruma `cards` (painéis/renderables) numa GRADE de `cols` colunas, RESPONSIVA à largura.
    Terminal estreito (width<96) → empilha em 1 coluna. Painéis curtos alinham no topo da linha."""
    cards = [c for c in cards if c is not None]
    if width and width < 96:
        cols = 1
    g = Table.grid(expand=True, padding=(0, gutter, 1, gutter))
    for _ in range(cols):
        g.add_column(ratio=1, overflow="fold")
    for i in range(0, len(cards), cols):
        chunk = list(cards[i:i + cols])
        while len(chunk) < cols:
            chunk.append("")
        g.add_row(*chunk)
    return g


def meter(ratio: float, *, width: int = 14, color: str = "") -> Text:
    """Barra horizontal █░ com cor por LIMIAR (verde<70% · âmbar<90% · vermelho≥90%) ou cor fixa."""
    r = 0.0 if ratio != ratio else max(0.0, min(1.0, ratio))   # NaN-safe
    filled = round(r * width)
    c = color or (GREEN if r < 0.7 else AMBER if r < 0.9 else RED)
    t = Text()
    t.append("█" * filled, style=c)
    t.append("░" * (width - filled), style=DIM)
    return t


def meter_rows(rows, *, bar_width: int = 14, label_w: int = 0) -> Table:
    """Linhas com MEDIDOR: `label  ████░░░  valor  flag`. `rows`: [(label, ratio, valor, flag?, color?)].
    valor/flag podem ser str ou Text; ratio∈[0,1] define a barra (cor por limiar, ou `color` fixa)."""
    g = Table.grid(padding=(0, 2, 0, 0))
    g.add_column(justify="left", style=MUTE, no_wrap=True, min_width=label_w)
    g.add_column(no_wrap=True)                       # barra
    g.add_column(justify="right", style=FG, no_wrap=True)
    g.add_column(no_wrap=True)                       # flag
    for row in rows:
        label, ratio, value = row[0], row[1], row[2]
        flag = row[3] if len(row) > 3 else Text("")
        color = row[4] if len(row) > 4 else ""
        g.add_row(label, meter(ratio, width=bar_width, color=color),
                  value if isinstance(value, Text) else Text(str(value), style=FG),
                  flag if isinstance(flag, Text) else Text(str(flag), style=MUTE))
    return g


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
