"""Interface bonita do terminal (§13) — banner, painel de tools/skills e status bar.

É o "rosto" do `okami chat`: ao abrir, mostra o logo, o modelo/sessão e o que o agente sabe fazer
(tools + skills), igual ao Hermes. Tudo via Rich (já é dependência) — sem TUI full-screen, é um REPL
com visual caprichado (não trava input, funciona em qualquer terminal). ASCII do logo é unicode (o
stdout do CLI já é reconfigurado p/ UTF-8)."""

from __future__ import annotations

from pathlib import Path

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

# Wordmark OKAMI em bloco (figlet ANSI Shadow, 6 linhas — maior/com profundidade). Gradiente da marca.
_LOGO = [
    " ██████╗ ██╗  ██╗ █████╗ ███╗   ███╗██╗",
    "██╔═══██╗██║ ██╔╝██╔══██╗████╗ ████║██║",
    "██║   ██║█████╔╝ ███████║██╔████╔██║██║",
    "██║   ██║██╔═██╗ ██╔══██║██║╚██╔╝██║██║",
    "╚██████╔╝██║  ██╗██║  ██║██║ ╚═╝ ██║██║",
    " ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝",
]
# Gradiente da MARCA (igual ao logotipo Okami): laranja → ciano → magenta, da esquerda p/ a direita.
_BRAND_STOPS = ((0xFF, 0x75, 0x27), (0x00, 0xDF, 0xE8), (0xFF, 0x39, 0xD1))


def _grad_color(t: float) -> str:
    """Cor hex no ponto t∈[0,1] do gradiente laranja→ciano→magenta (fiel aos tons do logo)."""
    s = _BRAND_STOPS
    if t <= 0:
        r, g, b = s[0]
    elif t >= 1:
        r, g, b = s[2]
    elif t < 0.5:
        a, c, f = s[0], s[1], t / 0.5
        r, g, b = (round(a[i] + (c[i] - a[i]) * f) for i in range(3))
    else:
        a, c, f = s[1], s[2], (t - 0.5) / 0.5
        r, g, b = (round(a[i] + (c[i] - a[i]) * f) for i in range(3))
    return f"#{r:02x}{g:02x}{b:02x}"


def _grad_lines(art: list[str]) -> Group:
    """Cada linha de `art` colorida com o gradiente HORIZONTAL da marca (vazios ficam transparentes)."""
    rows = []
    for line in art:
        t = Text(no_wrap=True)
        n = max(1, len(line) - 1)
        for i, ch in enumerate(line):
            t.append(ch, style=None if ch in (" ", "⠀") else f"bold {_grad_color(i / n)}")
        rows.append(t)
    return Group(*rows)


def _brand_wordmark() -> Group:
    """Wordmark OKAMI (bloco) no gradiente da marca — estilo Hermes (wordmark, não mascote crua)."""
    return _grad_lines(_LOGO)


# Mascote: lobo geométrico (front view, low-poly) em braille — gerado por silhueta. okami = 狼.
_WOLF = [
    "⠀⠀⠀⠀⣴⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣦",
    "⠀⠀⠀⢠⣿⣷⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣾⣿⡄",
    "⠀⠀⠀⣼⣿⣿⣧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣼⣿⣿⣧",
    "⠀⠀⢀⣿⣿⣿⣿⣧⠀⠀⣠⣶⣄⠀⠀⣠⣶⣄⠀⠀⣼⣿⣿⣿⣿⡀",
    "⠀⠀⣸⣿⣿⣿⣿⣿⣧⣾⣿⣿⣿⣦⣴⣿⣿⣿⣷⣼⣿⣿⣿⣿⣿⣇",
    "⠀⢀⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡀",
    "⠀⢸⣿⣿⣿⣿⣿⣿⣿⣿⠿⣿⣿⣿⣿⣿⣿⠿⣿⣿⣿⣿⣿⣿⣿⣿⡇",
    "⠀⠀⢿⣿⣿⣿⣿⣿⣍⡀⠀⣿⣿⣿⣿⣿⣿⠀⢀⣩⣿⣿⣿⣿⣿⡿",
    "⠀⠀⠈⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠁",
    "⠀⠀⠀⠘⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠃",
    "⠀⠀⠀⠀⠈⢿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠁",
    "⠀⠀⠀⠀⠀⠀⠙⣿⣿⠟⠁⢸⣿⣿⣿⣿⡇⠈⠻⣿⣿⠋",
    "⠀⠀⠀⠀⠀⠀⠀⠈⠁⠀⠀⠸⣿⣿⣿⣿⠇",
    "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿⣿⣿",
    "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠹⣿⣿⠏",
]


def _wolf_hero() -> Group:
    """Lobo geométrico no gradiente da marca — fallback se o PNG/Pillow não estiver disponível."""
    return _grad_lines(_WOLF)


from functools import lru_cache  # noqa: E402


@lru_cache(maxsize=4)
def _emblem_hero(cols: int = 50):
    """O LOGO REAL da Okami (emblema lobo+circuito) renderizado em half-block (cor de verdade).

    Cada caractere ▀/▄ carrega 2 pixels (fg=cima, bg=baixo) → cor cheia + 2× a resolução vertical;
    transparente (fora do logo) fica no fundo do terminal. Pillow ausente / PNG sumiu → None (cai no lobo)."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 — sem Pillow: o chamador usa o lobo geométrico
        return None
    png = Path(__file__).parent / "assets" / "okami_logo.png"
    if not png.exists():
        return None
    try:
        im = Image.open(png).convert("RGBA")
        w0, h0 = im.size
        em = im.crop((0, 0, w0, int(h0 * 0.63)))       # só o EMBLEMA (acima do wordmark "OKAMI")
        em = em.crop(em.getbbox())                      # corta o transparente em volta
        w, h = em.size
        rows = max(1, round(cols * (h / w) / 2))        # /2: cada linha = 2 px (half-block)
        em = em.resize((cols, rows * 2), Image.LANCZOS)
        px = em.load()
        lines = []
        for y in range(rows):
            t = Text(no_wrap=True)
            for x in range(cols):
                tr, tg, tb, ta = px[x, 2 * y]
                br, bg, bb, ba = px[x, 2 * y + 1]
                top, bot = ta > 70, ba > 70
                if top and bot:
                    t.append("▀", style=f"#{tr:02x}{tg:02x}{tb:02x} on #{br:02x}{bg:02x}{bb:02x}")
                elif top:
                    t.append("▀", style=f"#{tr:02x}{tg:02x}{tb:02x}")
                elif bot:
                    t.append("▄", style=f"#{br:02x}{bg:02x}{bb:02x}")
                else:
                    t.append(" ")
            lines.append(t)
        return Group(*lines)
    except Exception:  # noqa: BLE001 — qualquer pepino no decode → fallback
        return None


def hero(cols: int = 50):
    """O hero do startup: logo REAL se der, senão o lobo geométrico no gradiente."""
    return _emblem_hero(cols) or _wolf_hero()

# Buckets p/ agrupar as tools por domínio (como o "Available Tools" do Hermes).
_TOOL_BUCKETS = [
    ("arquivos", ["read_file", "write_file", "edit_file", "list_dir", "find_files"]),
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


def _route_repl_line(line: str, *, busy: bool, pending_approval: bool) -> str:
    """Decisão PURA de roteamento do chat concorrente (REPL e TUI compartilham; testável sem terminal).

    Retorna: exit · help · details · agents · skin · mouse · approval · stop · queue · handle.
    - comandos de DISPLAY (help/details/agents) são CLIENTE — não vão pro endpoint;
    - aprovação pendente tem prioridade (a próxima linha responde o go/no-go);
    - /stop sempre passa direto (cancela mesmo ocupado);
    - digitou enquanto ocupado → `queue` (vai pra fila FIFO, processa quando terminar)."""
    low = line.strip().lower()
    head = low.split(maxsplit=1)[0] if low else ""
    if low in ("/exit", "/quit", "exit", "quit", ":q"):
        return "exit"
    if low == "/help":
        return "help"
    if head == "/details":                              # verbosidade dos tool-calls (cliente)
        return "details"
    if head in ("/agents", "/tasks"):                   # painel de atividade (cliente)
        return "agents"
    if head == "/skin":                                 # tema da TUI (cliente)
        return "skin"
    if head == "/mouse":                                # mouse on/off (cliente)
        return "mouse"
    if pending_approval:
        return "approval"
    if low in ("/stop", "/cancel", "/parar"):
        return "stop"
    if busy:
        return "queue"
    return "handle"


def banner(version: str) -> Group:
    """Wordmark OKAMI multilinha no gradiente da marca."""
    return _brand_wordmark()


def _meta_block(model: str, provider: str, cwd: Path, session: str, agent: str) -> Group:
    """Coluna da esquerda do painel: estado da sessão (o hero agora é o logo, acima do painel)."""
    info = Text()
    info.append(f" {agent}", style=f"bold {ORANGE}")
    info.append("   ● operacional", style="green")
    info.append(f"\n {model}", style=FG)
    info.append(f"\n {provider}", style=MUTE)
    info.append(f"\n {cwd}", style=CYAN)
    info.append(f"\n sessão: {session}", style=DIM)
    return Group(info)


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
    """Tela de boas-vindas: LOGO ao lado do nome (header) → painel de ferramentas/skills → dicas."""
    # tagline + meta da sessão, que ficam À DIREITA do logo (ao lado, não embaixo).
    tag = Text()
    tag.append("CUSTOM SOLUTIONS", style=f"bold {ORANGE}")
    tag.append(" · ", style=DIM)
    tag.append("AI INNOVATION", style=f"bold {MAGENTA}")
    meta = Text()
    meta.append(f"{agent} ", style=f"bold {ORANGE}")
    meta.append("● operacional", style="green")
    meta.append(f"   {model}", style=FG)
    meta.append(f"  ·  {provider}", style=MUTE)
    meta.append(f"\nsessão {session}  ·  {cwd}", style=DIM)
    right = Group(banner(version), Text(""), tag, Text(""), meta)
    header = Table.grid(padding=(0, 3))               # LOGO | (wordmark + tagline + sessão), centrados na vertical
    header.add_column(justify="left", vertical="middle")
    header.add_column(justify="left", vertical="middle")
    header.add_row(hero(43), right)

    footer = Text(f"{len(tools)} ferramentas · {len(skills)} skills · /help para comandos",
                  style=MUTE, justify="center")
    panel = Panel(Group(_tools_skills(tools, skills), Text(""), footer), border_style=ORANGE,
                  title=f"[bold {ORANGE}]Okami Agent[/] [{DIM}]v{version}[/]", title_align="center")
    tips = Text()
    tips.append("\nBem-vindo ao Okami! ", style=f"bold {FG}")
    tips.append("Digite sua mensagem, ou /help para os comandos.", style=SOFT)
    if resumed:
        tips.append(f"\n↻ retomando conversa ({resumed} trocas anteriores)", style=MUTE)
    tips.append("\n✦ /persona <preset> muda o tom · /feedback molda o jeito dele falar.", style=MUTE)
    return Group(header, Text(""), panel, tips)


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


def _args_full(args: dict) -> str:
    """Todos os args numa linha (k=v) p/ o modo /details expanded — sem truncar tão cedo."""
    if not isinstance(args, dict) or not args:
        return ""
    parts = []
    for k, v in args.items():
        sv = str(v).replace("\n", " ")
        parts.append(f"{k}={sv[:120] + ('…' if len(sv) > 120 else '')}")
    return " · ".join(parts)[:240]


_DETAIL_LEVELS = ("hidden", "collapsed", "expanded")

# Temas da TUO (/skin): 'okami' é a marca (registrado no app); o resto são temas embutidos do Textual.
SKINS = ("okami", "nord", "gruvbox", "dracula", "tokyo-night", "monokai", "textual-light")


def activity_panel(*, bg: dict | None = None, busy: bool = False, queued: int = 0,
                   procs: list | None = None) -> Text:
    """Painel /agents (alias /tasks): o que roda AGORA — turno, /background, fila E processos OS."""
    bg = bg or {}
    procs = procs or []
    t = Text()
    t.append("⚙ atividade\n", style=f"bold {CYAN}")
    t.append("  turno atual: ", style=MUTE)
    t.append(("ocupado" if busy else "livre") + "\n", style=ORANGE if busy else SOFT)
    if bg:
        t.append(f"  background ({len(bg)}):\n", style=MUTE)
        for bid, desc in list(bg.items())[:10]:
            t.append(f"    ▶ #{bid} {desc}\n", style=SOFT)
    else:
        t.append("  background: nenhum\n", style=MUTE)
    running = [p for p in procs if p.get("status") == "running"]
    if procs:                                            # processos OS (servidor/build) — kill real: /process kill
        t.append(f"  processos ({len(running)} ativos / {len(procs)}):\n", style=MUTE)
        for p in procs[-8:]:
            sym = "▶" if p.get("status") == "running" else "✅" if p.get("status") == "exited" else "·"
            t.append(f"    {sym} {p.get('id', '?')} {(p.get('cmd') or '')[:40]}\n", style=SOFT)
    if queued:
        t.append(f"  fila: {queued} aguardando\n", style="#ffb86c")
    return t


# ── Emojis p/ leitura visual INSTANTÂNEA do que o agente faz (pedido do usuário: tool→🛠️, etc.). ──
# Por FERRAMENTA (categoria) — "que tipo de coisa está rolando agora":
_TOOL_EMOJI = {
    "run_shell": "🐚",
    "read_file": "📖", "list_dir": "📂", "find_files": "🔎",
    "write_file": "✍️", "edit_file": "✏️",
    "remember": "🧠", "recall_memory": "🧠", "remember_user": "🧠",
    "use_skill": "✨", "spawn": "🤖", "browse": "🌐", "generate_image": "🎨", "need_input": "❓",
    "process_start": "🐚", "process_write": "⌨️", "process_poll": "🐚", "process_wait": "⏳",
    "process_log": "📜", "process_list": "📋", "process_kill": "🛑", "process_signal": "🛑",
}


def tool_emoji(tool: str) -> str:
    """Emoji da CATEGORIA de uma tool (🛠️ genérico p/ desconhecida). Reuso TUI + REPL."""
    if tool in _TOOL_EMOJI:
        return _TOOL_EMOJI[tool]
    t = (tool or "").lower()
    if t.startswith("process_") or any(k in t for k in ("shell", "exec", "bash")):
        return "🐚"
    if any(k in t for k in ("search", "grep", "glob", "find")):
        return "🔎"
    if any(k in t for k in ("read", "cat", "open", "view")):
        return "📖"
    if any(k in t for k in ("write", "edit", "patch", "create", "apply")):
        return "✍️"
    if any(k in t for k in ("memor", "remember", "recall")):
        return "🧠"
    if any(k in t for k in ("browse", "fetch", "http", "web", "url")):
        return "🌐"
    if "git" in t:
        return "🌿"
    if "test" in t:
        return "🧪"
    return "🛠️"


def author_rule(name: str, *, color: str, when: str = ""):
    """Separador de turno FORTE: régua horizontal com a barra ▌ + nome + hora, na cor do autor, que
    CRUZA a tela. Resolve 'a corzinha do lado do nome não basta' mantendo um visual SÓBRIO/profissional
    (a barra ▌, não emoji de avatar — emoji no nome passa 'projeto de garagem')."""
    from rich.rule import Rule
    title = Text()
    title.append("▌ ", style=f"bold {color}")
    title.append(name, style=f"bold {color}")
    if when:
        title.append(f"  {when}", style=MUTE)
    return Rule(title=title, align="left", characters="─", style=color)


def event_line(e: dict, detail: str = "collapsed") -> Text | None:
    """Linha ao vivo p/ um evento do harness (tool-call, loop, compaction…). None = não mostrar.

    É o que faz o terminal sentir VIVO: em vez de 'pensando…' por 30s e cuspir tudo, mostra cada
    passo enquanto acontece — agora com EMOJI por tipo (🛠️ tool · 🔁 loop · 🧠 escalar…) p/ você bater
    o olho e saber o que tá rolando. `detail` (/details): hidden = só o final · collapsed = 1 linha por
    passo (default) · expanded = com os args."""
    k = e.get("kind")
    if k == "step":
        if detail == "hidden":                          # /details hidden → não polui com tool-calls
            return None
        args = e.get("args") or {}
        prev = _args_full(args) if detail == "expanded" else _args_preview(args)
        emoji = tool_emoji(e["tool"])                   # 🛠️/🐚/📖/✍️… = QUE tipo de coisa o agente faz
        markc, mark = (CYAN, "✓") if e.get("ok") else ("red", "✗")
        t = Text.from_markup(f"  {emoji} [{markc}]{mark}[/] [{SOFT}]{e['tool']}[/]"
                             + (f" [{MUTE}]{prev}[/]" if prev else ""))
        return t
    if k == "approval_request":
        return Text.from_markup(f"  🔐 [{ORANGE}]aprovação:[/] [{SOFT}]{e.get('reason', '')}[/]")
    if k == "loop":
        return Text.from_markup(f"  🔁 [{ORANGE}]loop detectado[/] [{MUTE}](x{e.get('repeats', '?')})[/]")
    if k == "stall":
        return Text.from_markup("  🤔 [%s]sem progresso, mudando de abordagem[/]" % ORANGE)
    if k == "escalate":
        return Text.from_markup(f"  🧠 [{MAGENTA}]escalando p/ modelo mais forte[/] [{MUTE}]({e.get('why', '')})[/]")
    if k == "compact":
        return Text.from_markup(f"  🗜️ [{CYAN}]compactando contexto[/] [{MUTE}]({e.get('promoted', 0)} → memória)[/]")
    if k == "complete_rejected":
        miss = ", ".join(e.get("missing", []))
        return Text.from_markup(f"  🚧 [{ORANGE}]ainda falta:[/] [{SOFT}]{miss}[/]")
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


def command_matches(typed: str, *, limit: int = 12):
    """[(label, name)] dos slash commands (chat) que casam com o digitado depois de '/'. [] = nenhum.
    `label` é um Text bonito (/nome args — descrição); `name` é o nome canônico p/ completar o input."""
    s = (typed or "").lstrip()
    if not s.startswith("/") or " " in s:            # só enquanto digita o NOME do comando (sem args)
        return []
    from okami import commands as _cmds
    partial = s[1:].lower()
    out = []
    for c in _cmds.COMMAND_REGISTRY:
        if c.scope not in ("chat", "both"):
            continue
        if partial and not any(n.startswith(partial) for n in (c.name, *c.aliases)):
            continue
        lbl = Text(no_wrap=True, overflow="ellipsis")
        lbl.append("/" + c.name, style=f"bold {MAGENTA}")
        if c.args:
            lbl.append(f" {c.args}", style=MUTE)
        lbl.append(f"   {_cmds.desc_of(c)}", style=SOFT)
        out.append((lbl, c.name))
        if len(out) >= limit:
            break
    return out


def command_hints(typed: str, *, limit: int = 8):
    """Autocomplete do TUI: comandos que casam com o que foi digitado depois de '/'. None = não mostrar
    (não começa com '/' ou já está digitando argumentos). Devolve um renderable p/ o painel popup."""
    s = (typed or "").lstrip()
    if not s.startswith("/") or " " in s:            # só enquanto digita o NOME do comando (sem args)
        return None
    from okami import commands as _cmds
    partial = s[1:].lower()
    hits = [c for c in _cmds.COMMAND_REGISTRY
            if c.scope in ("chat", "both")
            and (not partial or any(n.startswith(partial) for n in (c.name, *c.aliases)))]
    if not hits:
        return None
    t = Text(no_wrap=True, overflow="ellipsis")
    t.append(" ⌨ comandos", style=f"bold {CYAN}")
    t.append(f"  (/{partial}…)\n" if partial else "  (↵ envia · → completa)\n", style=MUTE)
    for c in hits[:limit]:
        t.append("  /" + c.name, style=f"bold {MAGENTA}")
        if c.args:
            t.append(f" {c.args}", style=MUTE)
        t.append(f"   {_cmds.desc_of(c)}\n", style=SOFT)
    if len(hits) > limit:
        t.append(f"  …+{len(hits) - limit} mais\n", style=MUTE)
    return t


def help_table() -> Table:
    """Tabela dos slash commands — gerada do REGISTRO declarativo (okami/commands.py). Localizada."""
    from okami import commands as _cmds
    from okami.i18n import t as _t
    t = Table(title=_t("tui.help.title"), border_style=ORANGE, title_style=f"bold {ORANGE}")
    t.add_column(_t("tui.help.col.category"), style=f"bold {CYAN}")
    t.add_column(_t("tui.help.col.command"), style=f"bold {MAGENTA}")
    t.add_column(_t("tui.help.col.does"), style=SOFT)
    for cat, cmds in _cmds.by_category().items():
        for i, c in enumerate(cmds):
            name = "/" + c.name + (f" {c.args}" if c.args else "")
            if c.aliases:
                name += f"  ({', '.join('/' + a for a in c.aliases)})"
            t.add_row(_cmds.category_label(cat) if i == 0 else "", name, _cmds.desc_of(c))
    return t
