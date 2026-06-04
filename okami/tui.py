"""Interface bonita do terminal (§13) — banner, painel de tools/skills e status bar.

É o "rosto" do `okami chat`: ao abrir, mostra o logo, o modelo/sessão e o que o agente sabe fazer
(tools + skills), igual ao Hermes. Tudo via Rich (já é dependência) — sem TUI full-screen, é um REPL
com visual caprichado (não trava input, funciona em qualquer terminal). ASCII do logo é unicode (o
stdout do CLI já é reconfigurado p/ UTF-8)."""

from __future__ import annotations

from pathlib import Path

from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Paleta da MARCA Okami (design-system v0.2): Onyx/Bone + acentos OKLCH → hex.
ORANGE = "#ff7527"      # Heat Orange — acento primário/interativo
MAGENTA = "#ff39d1"     # Neon Magenta — acento
CYAN = "#00dfe8"        # Volt Cyan — foco/links
FG = "#f4f4f8"          # Bone — texto
SOFT = "#b9bac8"        # fg-soft
MUTE = "#6c6d80"        # fg-mute — secundário
DIM = "#3d3e50"         # fg-dim
TAGLINE = "IA com soberania para PMEs"

# Logo em bloco (5 linhas). Gradiente laranja→magenta (o "glow" contido da marca).
_LOGO = [
    " ██████  ██   ██  █████  ███    ███ ██",
    "██    ██ ██  ██  ██   ██ ████  ████ ██",
    "██    ██ █████   ███████ ██ ████ ██ ██",
    "██    ██ ██  ██  ██   ██ ██  ██  ██ ██",
    " ██████  ██   ██ ██   ██ ██      ██ ██",
]
_LOGO_COLORS = ["#ff7115", "#ff6757", "#ff6382", "#ff64a8", "#f269cb"]

# Mascote (lobo — okami = 狼).
_WOLF = [
    "   /\\___/\\",
    "  ( o   o )",
    "  (  =^=  )",
    "   )     (",
    "  (       )",
    "  (__)_(__)",
]

# Buckets p/ agrupar as tools por domínio (como o "Available Tools" do Hermes).
_TOOL_BUCKETS = [
    ("arquivos", ["read_file", "write_file", "list_dir"]),
    ("shell", ["run_shell"]),
    ("memória", ["remember", "recall_memory", "remember_user"]),
    ("skills", ["use_skill"]),
    ("agentes", ["spawn"]),
    ("browser", ["browse"]),
    ("mídia", ["generate_image"]),
]

# Inferência leve de categoria de skill (deixa o painel rico mesmo sem `category:` no frontmatter).
_SKILL_CATS = [
    ("creative", ["design", "landing", "prototyp", "protótip", "ascii", "diagram", "ui", "ux",
                  "frontend", "heroui", "shadcn", "image", "infografic"]),
    ("docs", ["wiki", "doc", "write", "plan", "page"]),
    ("agents", ["delegate", "claude", "codex", "kanban", "orchestr", "agent", "proactive", "proativ"]),
    ("memory", ["memory", "honcho", "remember", "memó"]),
    ("comms", ["communicat", "humaniz", "writing", "comunic"]),
    ("dev", ["tdd", "test", "debug", "lint", "git"]),
]


def _skill_category(s) -> str:
    """category: do frontmatter, senão infere por nome/triggers (fallback 'geral')."""
    cat = (getattr(s, "meta", {}) or {}).get("category")
    if cat:
        return str(cat)
    hay = (s.name + " " + " ".join(getattr(s, "triggers", []) or [])).lower()
    for label, kws in _SKILL_CATS:
        if any(k in hay for k in kws):
            return label
    return "geral"


def banner(version: str) -> Text:
    """Logo OKAMI multilinha, centralizado e colorido."""
    t = Text(justify="center")
    for line, color in zip(_LOGO, _LOGO_COLORS):
        t.append(line + "\n", style=f"bold {color}")
    return t


def _meta_block(model: str, provider: str, cwd: Path, session: str, agent: str) -> Group:
    """Coluna da esquerda: mascote + estado da sessão."""
    wolf = Text("\n".join(_WOLF), style=f"bold {ORANGE}")
    info = Text()
    info.append(f"\n {agent}", style=f"bold {ORANGE}")
    info.append("   ● operacional", style="green")
    info.append(f"\n {model}", style=FG)
    info.append(f"\n {provider}", style=MUTE)
    info.append(f"\n {cwd}", style=CYAN)
    info.append(f"\n sessão: {session}", style=DIM)
    return Group(Align.center(wolf), info)


def _tools_skills(tools: list[str], skills: list) -> Group:
    """Coluna da direita: Available Tools (por bucket) + Available Skills (por categoria)."""
    body = Text()
    body.append("Ferramentas\n", style=f"bold {CYAN}")
    known = set()
    for label, names in _TOOL_BUCKETS:
        present = [n for n in names if n in tools]
        if not present:
            continue
        known.update(present)
        body.append(f"  {label}: ", style=MUTE)
        body.append(", ".join(present) + "\n", style=SOFT)
    extra = [t for t in tools if t not in known and not t.startswith("task_") and t != "need_input"]
    if extra:
        body.append("  outras: ", style=MUTE)
        body.append(", ".join(extra) + "\n", style=SOFT)

    body.append("\nSkills\n", style=f"bold {CYAN}")
    by_cat: dict[str, list[str]] = {}
    for s in skills:
        by_cat.setdefault(_skill_category(s), []).append(s.name)
    for cat in sorted(by_cat):
        names = sorted(by_cat[cat])
        shown = ", ".join(names[:5]) + (f" … (+{len(names) - 5})" if len(names) > 5 else "")
        body.append(f"  {cat}: ", style=MUTE)
        body.append(shown + "\n", style=SOFT)
    return Group(body)


def welcome(*, version: str, model: str, provider: str, cwd: Path, session: str, agent: str,
            tools: list[str], skills: list, resumed: int = 0) -> Group:
    """Tela de boas-vindas completa (logo + painel com 2 colunas + dicas)."""
    left = _meta_block(model, provider, cwd, session, agent)
    right = _tools_skills(tools, skills)
    grid = Table.grid(padding=(0, 3))                 # 2 colunas lado a lado (determinístico)
    grid.add_column(width=22, justify="left")
    grid.add_column(ratio=1, justify="left")
    grid.add_row(left, right)
    footer = Text(f"{len(tools)} ferramentas · {len(skills)} skills · /help para comandos",
                  style=MUTE, justify="center")
    panel = Panel(Group(grid, Text(""), footer), border_style=ORANGE,
                  title=f"[bold {ORANGE}]Okami Agent[/] [{DIM}]v{version}[/]", title_align="center")
    tag = Text(f"{TAGLINE.upper()}", style=f"{CYAN}", justify="center")  # tagline da marca
    rule = Text("─" * 38, style=DIM, justify="center")
    tips = Text()
    tips.append("\nBem-vindo ao Okami! ", style=f"bold {FG}")
    tips.append("Digite sua mensagem, ou /help para os comandos.", style=SOFT)
    if resumed:
        tips.append(f"\n↻ retomando conversa ({resumed} trocas anteriores)", style=MUTE)
    tips.append("\n✦ /persona <preset> muda o tom · /feedback molda o jeito dele falar.", style=MUTE)
    return Group(Align.center(banner(version)), Align.center(tag), Align.center(rule), panel, tips)


def _args_preview(args: dict) -> str:
    """1 linha curta dos args de uma tool (path/cmd/query) p/ o display ao vivo."""
    if not isinstance(args, dict):
        return ""
    for k in ("path", "cmd", "query", "url", "name", "text", "goal"):
        v = args.get(k)
        if isinstance(v, str) and v:
            v = v.replace("\n", " ")
            return v[:60] + ("…" if len(v) > 60 else "")
    return ""


def event_line(e: dict) -> Text | None:
    """Linha ao vivo p/ um evento do harness (tool-call, loop, compaction…). None = não mostrar.

    É o que faz o terminal sentir VIVO: em vez de 'pensando…' por 30s e cuspir tudo, mostra cada
    passo enquanto acontece. Mesmos eventos que o `okami task` já renderiza — agora no chat também."""
    k = e.get("kind")
    if k == "step":
        prev = _args_preview(e.get("args") or {})
        mark = f"[{CYAN}]✓[/]" if e.get("ok") else f"[red]✗[/]"
        t = Text.from_markup(f"  {mark} [{SOFT}]{e['tool']}[/]" + (f" [{MUTE}]{prev}[/]" if prev else ""))
        return t
    if k == "approval_request":
        return Text.from_markup(f"  [{ORANGE}]⚠ aprovação:[/] [{SOFT}]{e.get('reason', '')}[/]")
    if k == "loop":
        return Text.from_markup(f"  [{ORANGE}]⟲ loop detectado[/] [{MUTE}](x{e.get('repeats', '?')})[/]")
    if k == "stall":
        return Text.from_markup(f"  [{ORANGE}]… sem progresso, mudando de abordagem[/]")
    if k == "escalate":
        return Text.from_markup(f"  [{MAGENTA}]⬆ escalando p/ modelo mais forte[/] [{MUTE}]({e.get('why', '')})[/]")
    if k == "compact":
        return Text.from_markup(f"  [{CYAN}]⊟ compactando contexto[/] [{MUTE}]({e.get('promoted', 0)} → memória)[/]")
    if k == "complete_rejected":
        miss = ", ".join(e.get("missing", []))
        return Text.from_markup(f"  [{ORANGE}]✗ ainda falta:[/] [{SOFT}]{miss}[/]")
    return None


def status_bar(*, model: str, ctx_pct: int, turns: int, elapsed: float) -> Text:
    """Barra de status compacta (impressa antes de cada prompt) — modelo · contexto · trocas · tempo."""
    bar_len = 12
    filled = max(0, min(bar_len, round(bar_len * ctx_pct / 100)))
    gauge = "█" * filled + "░" * (bar_len - filled)
    t = Text()
    t.append(" ⬡ ", style=f"bold {ORANGE}")
    t.append(model, style=f"bold {FG}")
    t.append("  ctx ", style=MUTE)
    t.append(f"{gauge} {ctx_pct:>3}%", style=CYAN if ctx_pct < 80 else "red")
    t.append(f"  · {turns} trocas", style=MUTE)
    if elapsed:
        t.append(f"  · ⏱ {elapsed:.0f}s", style=MUTE)
    return t


def help_table() -> Table:
    """Tabela dos slash commands (resposta do /help)."""
    t = Table(title="Comandos", border_style=ORANGE, title_style=f"bold {ORANGE}")
    t.add_column("comando", style=f"bold {MAGENTA}")
    t.add_column("o que faz", style=SOFT)
    rows = [
        ("/help", "mostra esta ajuda"),
        ("/new", "começa uma conversa nova (arquiva a atual)"),
        ("/status", "estado da sessão (trocas, yolo)"),
        ("/stop", "cancela a tarefa em andamento"),
        ("/yolo · /normal", "liga/desliga auto-aprovação de ações sensíveis"),
        ("/feedback <texto>", "molda o jeito do agente falar (evolui VOICE/PERSONA)"),
        ("/persona <preset>", "muda o tom só nesta sessão (/persona off volta)"),
        ("/think <nível>", "esforço de raciocínio: minimal·low·medium·high (/think off = default)"),
        ("/undo", "reverte a última evolução de identidade"),
        ("/retry", "retoma uma tarefa interrompida"),
        ("/exit", "sai do chat (ou Ctrl-D)"),
    ]
    for c, d in rows:
        t.add_row(c, d)
    return t
