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

from okami.i18n import t as _tr      # i18n: EN default, PT via OKAMI_LANG=pt (`t` colide c/ a var local Text)

# Paleta da MARCA Okami (design-system v0.2): Onyx/Bone + acentos OKLCH → hex.
ORANGE = "#ff7527"      # Heat Orange — acento primário/interativo
MAGENTA = "#ff39d1"     # Neon Magenta — acento
CYAN = "#00dfe8"        # Volt Cyan — foco/links
FG = "#f4f4f8"          # Bone — texto
SOFT = "#b9bac8"        # fg-soft
MUTE = "#6c6d80"        # fg-mute — secundário
DIM = "#3d3e50"         # fg-dim
DIFF_ADD = "#1f7a3d"    # verde — linha adicionada no diff
DIFF_DEL = "#c14545"    # vermelho — linha removida no diff
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


def _route_repl_line(line: str, *, busy: bool, pending_approval: bool = False,
                     pending_clarify: bool = False) -> str:
    """Decisão PURA de roteamento do chat concorrente (REPL e TUI compartilham; testável sem terminal).

    Retorna: exit · help · details · agents · skin · mouse · copy · approval · clarify · stop · queue · handle.
    - comandos de DISPLAY (help/details/agents) são CLIENTE — não vão pro endpoint;
    - aprovação pendente tem prioridade (a próxima linha responde o go/no-go);
    - clarify pendente (turno bloqueado esperando resposta) → a linha responde DIRETO (não vai pra fila);
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
    if head in ("/replay", "/last"):                    # M8: últimos tool-calls c/ args+saída (cliente)
        return "replay"
    if head == "/skin":                                 # tema da TUI (cliente)
        return "skin"
    if head == "/mouse":                                # mouse on/off (cliente)
        return "mouse"
    if head == "/copy":                                 # copia a última resposta p/ o clipboard (cliente)
        return "copy"
    if pending_approval:
        return "approval"
    if pending_clarify:                                 # turno bloqueado numa pergunta → responde direto
        return "clarify"
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
    tips.append("\n" + _tr("welcome.hi", _default="Welcome to Okami! "), style=f"bold {FG}")
    tips.append(_tr("welcome.type", _default="Type your message, or /help for commands."), style=SOFT)
    if resumed:
        tips.append("\n" + _tr("welcome.resumed", _default="↻ resuming conversation ({resumed} prior turns)",
                                resumed=resumed), style=MUTE)
    tips.append("\n" + _tr("welcome.persona", _default="✦ /persona <preset> shifts the tone · /feedback shapes "
                           "how it talks."), style=MUTE)
    tips.append("\n" + _tr("welcome.copy", _default="🖱 drag to select and copy NORMALLY (Cmd/Ctrl+C — native "
                           "terminal selection) · /copy copies the whole last reply."), style=MUTE)
    try:                                          # #9: dica do dia (corpus rotativo de descoberta)
        from datetime import date
        from okami.core.tips import get_tip
        tips.append("\n💡 " + get_tip(seed=date.today().toordinal()), style=MUTE)
    except Exception:  # noqa: BLE001 — dica é cosmética
        pass
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


# args cujo VALOR é segredo (store_secret, etc.) — nunca mostrar no /details expanded (vaza credencial).
_SECRET_ARG_KEYS = frozenset({"value", "secret", "password", "passwd", "pwd", "token",
                              "api_key", "apikey", "credential", "app_password"})


def _args_full(args: dict) -> str:
    """Todos os args numa linha (k=v) p/ o modo /details expanded — sem truncar tão cedo.
    Args de credencial (value/token/password/…) saem MASCARADOS: o expanded não pode vazar segredo."""
    if not isinstance(args, dict) or not args:
        return ""
    parts = []
    for k, v in args.items():
        if str(k).lower() in _SECRET_ARG_KEYS:
            parts.append(f"{k}=«oculto»")
            continue
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
    t.append(_tr("activity.title", _default="⚙ activity") + "\n", style=f"bold {CYAN}")
    t.append("  " + _tr("activity.current_turn", _default="current turn: "), style=MUTE)
    t.append((_tr("activity.busy", _default="busy") if busy else _tr("activity.idle", _default="idle")) + "\n",
             style=ORANGE if busy else SOFT)
    if bg:
        t.append(f"  background ({len(bg)}):\n", style=MUTE)
        for bid, desc in list(bg.items())[:10]:
            t.append(f"    ▶ #{bid} {desc}\n", style=SOFT)
    else:
        t.append("  " + _tr("activity.bg_none", _default="background: none") + "\n", style=MUTE)
    running = [p for p in procs if p.get("status") == "running"]
    if procs:                                            # processos OS (servidor/build) — kill real: /process kill
        t.append("  " + _tr("activity.processes", _default="processes", ) + f" ({len(running)}/{len(procs)}):\n",
                 style=MUTE)
        for p in procs[-8:]:
            sym = "▶" if p.get("status") == "running" else "✅" if p.get("status") == "exited" else "·"
            t.append(f"    {sym} {p.get('id', '?')} {(p.get('cmd') or '')[:40]}\n", style=SOFT)
    if queued:
        t.append("  " + _tr("activity.queue", _default="queue: {n} waiting", n=queued) + "\n", style="#ffb86c")
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


# Verbo que ROTACIONA enquanto a agente pensa (paridade FaceTicker do Hermes: em vez de "pensando…"
# fixo por 30s, o verbo muda devagar e dá sensação de vida). _THINK_EVERY ticks por verbo (~2s a 0.12s/tick).
_THINK_VERBS = ("raciocinando", "vasculhando o código", "ligando os pontos", "pensando alto",
                "montando o plano", "lendo com calma", "cruzando os fatos", "afiando a resposta",
                "investigando", "conferindo os detalhes")
_THINK_EVERY = 16


def thinking_phrase(tick: int) -> str:
    """Verbo do indicador de 'pensando' para o tick atual — rotaciona devagar (FaceTicker do Hermes)."""
    return _THINK_VERBS[(int(tick) // _THINK_EVERY) % len(_THINK_VERBS)]


def running_tool_text(tool: str, args: dict, *, spin: str = "", elapsed: int = 0):
    """Linha VIVA de uma tool RODANDO (emoji + spinner + nome + arg + relógio) — paridade Hermes: a tool
    aparece com spinner e duração ENQUANTO executa, não só depois com ✓/✗. Vai pro painel #activity (mutável
    a cada tick); o card final (com resultado) vai pro #log quando termina."""
    from rich.text import Text
    t = Text(no_wrap=True, overflow="ellipsis")
    t.append(f"  {tool_emoji(tool)} ", style="")
    if spin:
        t.append(f"{spin} ", style=f"bold {ORANGE}")
    t.append(str(tool), style=f"bold {SOFT}")
    prev = _args_preview(args or {})
    if prev:
        t.append(f" {prev}", style=MUTE)
    t.append(f"  {int(elapsed)}s", style=DIM)
    return t


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


def replay_view(steps: list[dict], n: int = 10):
    """/replay (M8): os últimos N tool-calls com args COMPLETOS + preview da saída — p/ inspecionar o que o
    agente fez (a vista ao vivo trunca/coalesce; aqui você 'reabre' a chamada que errou e vê tudo)."""
    from rich.console import Group
    from rich.markup import escape
    recent = [s for s in (steps or []) if s.get("kind") == "step"][-max(1, n):]
    if not recent:
        return Text.from_markup(f"[{MUTE}]↻ nenhum tool-call nesta sessão ainda.[/]")
    blocks: list = [Text.from_markup(f"[{ORANGE}]↻ últimos {len(recent)} tool-calls[/] [{MUTE}](/replay)[/]")]
    for s in recent:
        emoji = tool_emoji(s.get("tool", ""))
        mark, markc = ("✓", CYAN) if s.get("ok") else ("✗", "red")
        blocks.append(Text.from_markup(
            f"  {emoji} [{markc}]{mark}[/] [{SOFT}]{escape(str(s.get('tool', '?')))}[/] "
            f"[{MUTE}]{escape(_args_full(s.get('args') or {}))}[/]"))
        out = (s.get("out") or "").strip()
        if out:
            preview = out if len(out) <= 300 else out[:300] + " …"
            for ln in preview.splitlines() or [preview]:
                blocks.append(Text.from_markup(f"       [{MUTE}]{escape(ln)}[/]"))
    return Group(*blocks)


def event_line(e: dict, detail: str = "collapsed") -> Text | None:
    """Linha ao vivo p/ um evento do harness (tool-call, loop, compaction…). None = não mostrar.

    É o que faz o terminal sentir VIVO: em vez de 'pensando…' por 30s e cuspir tudo, mostra cada
    passo enquanto acontece — agora com EMOJI por tipo (🛠️ tool · 🔁 loop · 🧠 escalar…) p/ você bater
    o olho e saber o que tá rolando. `detail` (/details): hidden = só o final · collapsed = 1 linha por
    passo (default) · expanded = com os args."""
    from rich.markup import escape                       # CONTEÚDO dinâmico (cmd/args/razão) pode ter '[/]'/
    k = e.get("kind")                                     # '[x]' → escapa SEMPRE, senão from_markup quebra o turno
    if k == "step":                                       # (MarkupError "closing tag '[/]' …"). Tags de estilo
        if detail == "hidden":                            # ([cor]…[/]) ficam fora do escape, de propósito.
            return None
        args = e.get("args") or {}
        prev = _args_full(args) if detail == "expanded" else _args_preview(args)
        emoji = tool_emoji(e["tool"])                   # 🛠️/🐚/📖/✍️… = QUE tipo de coisa o agente faz
        markc, mark = (CYAN, "✓") if e.get("ok") else ("red", "✗")
        t = Text.from_markup(f"  {emoji} [{markc}]{mark}[/] [{SOFT}]{escape(str(e['tool']))}[/]"
                             + (f" [{MUTE}]{escape(str(prev))}[/]" if prev else ""))
        return t
    if k == "approval_request":
        return Text.from_markup(f"  🔐 [{ORANGE}]{_tr('event.approval', _default='approval:')}[/] "
                                f"[{SOFT}]{escape(str(e.get('reason', '')))}[/]")
    if k == "loop":
        return Text.from_markup(f"  🔁 [{ORANGE}]{_tr('event.loop', _default='loop detected')}[/] "
                                f"[{MUTE}](x{escape(str(e.get('repeats', '?')))})[/]")
    if k == "stall":
        return Text.from_markup(f"  🤔 [{ORANGE}]{_tr('event.stall', _default='no progress, changing approach')}[/]")
    if k == "escalate":
        return Text.from_markup(f"  🧠 [{MAGENTA}]{_tr('event.escalate', _default='escalating to a stronger model')}[/] "
                                f"[{MUTE}]({escape(str(e.get('why', '')))})[/]")
    if k == "compact":
        return Text.from_markup(f"  🗜️ [{CYAN}]{_tr('event.compact', _default='compacting context')}[/] "
                                f"[{MUTE}]({escape(str(e.get('promoted', 0)))} → {_tr('event.memory', _default='memory')})[/]")
    if k == "complete_rejected":
        miss = escape(", ".join(str(m) for m in e.get("missing", [])))
        return Text.from_markup(f"  🚧 [{ORANGE}]{_tr('event.still_missing', _default='still missing:')}[/] [{SOFT}]{miss}[/]")
    if k == "salvaged":                                  # turno ia falhar → ENTREGOU o parcial em vez de morrer
        return Text.from_markup(f"  🛟 [{ORANGE}]{_tr('event.salvaged', _default='partial delivery')}[/] "
                                f"[{MUTE}]({escape(str(e.get('reason', '')))})[/]")
    if k == "llm_call":                                  # torna o GARGALO visível: só as gerações LENTAS (>8s)
        secs = e.get("secs", 0) or 0
        if secs < 8:
            return None
        ti, to = int(e.get("tokens_in", 0)), int(e.get("tokens_out", 0))
        return Text.from_markup(f"  ⏱ [{MUTE}]{_tr('event.generation', _default='generation')} "
                                f"{secs:.0f}s · {ti // 1000}k↑ {to // 1000}k↓[/]")
    return None


_DIFF_MAX_LINES = 40       # diff maior que isto é capado (não despeja arquivo inteiro no log)


def diff_block(old: str, new: str, path: str = "", context: int = 2):
    """Diff colorido (verde +/ vermelho -) entre dois textos. Renderable do Rich. Capado em
    _DIFF_MAX_LINES p/ não inundar o log numa reescrita grande."""
    import difflib

    from rich.console import Group
    from rich.markup import escape
    old_lines = (old or "").splitlines()
    new_lines = (new or "").splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=context))
    body = [ln for ln in diff if not ln.startswith(("---", "+++", "@@"))]   # tira o cabeçalho do unified
    rows: list = []
    if path:
        import os
        uri = "file://" + os.path.abspath(path)      # item 8: path clicável (OSC-8 via Rich; degrada s/ TTY)
        label = (f"[link={uri}]{escape(path)}[/link]" if "[" not in uri and "]" not in uri
                 else escape(path))
        rows.append(Text.from_markup(f"  [{MUTE}]±[/] [{SOFT}]{label}[/]"))
    shown = body[:_DIFF_MAX_LINES]
    for ln in shown:
        if ln.startswith("+"):
            rows.append(Text(f"  + {ln[1:]}", style=DIFF_ADD))
        elif ln.startswith("-"):
            rows.append(Text(f"  - {ln[1:]}", style=DIFF_DEL))
        else:
            rows.append(Text(f"    {ln[1:] if ln[:1] == ' ' else ln}", style=MUTE))
    if len(body) > _DIFF_MAX_LINES:
        rows.append(Text.from_markup(f"  [{MUTE}]… +{len(body) - _DIFF_MAX_LINES} linhas (diff truncado)[/]"))
    return Group(*rows) if rows else Text("")


def _code_preview(text: str, lang: str = "", max_lines: int = 20):
    """Bloco de código com syntax highlight (Rich Syntax), capado em max_lines."""
    from rich.syntax import Syntax
    lines = (text or "").splitlines()
    body = "\n".join(lines[:max_lines])
    if len(lines) > max_lines:
        body += f"\n… +{len(lines) - max_lines} linhas"
    return Syntax(body, lang or "text", theme="ansi_dark", background_color="default", word_wrap=True)


def _lang_for(path: str) -> str:
    ext = (path or "").rsplit(".", 1)[-1].lower() if "." in (path or "") else ""
    return {"py": "python", "js": "javascript", "ts": "typescript", "sh": "bash", "json": "json",
            "yaml": "yaml", "yml": "yaml", "md": "markdown", "html": "html", "css": "css",
            "go": "go", "rs": "rust", "sql": "sql", "toml": "toml"}.get(ext, "text")


def tool_block(e: dict, detail: str = "collapsed"):
    """Card de um tool-call: a linha do event_line + (edição → DIFF colorido; escrita → conteúdo com
    syntax; leitura/shell → preview da saída no modo expanded). Eventos não-step caem no event_line."""
    if e.get("kind") != "step":
        return event_line(e, detail)
    line = event_line(e, detail)
    if line is None:                                       # detail=hidden → suprime o passo
        return None
    from rich.console import Group
    args = e.get("args") or {}
    tool = e.get("tool", "")
    extra: list = []
    if tool == "edit_file" and (args.get("old") or args.get("new")):
        extra.append(diff_block(str(args.get("old", "")), str(args.get("new", "")), path=str(args.get("path", ""))))
    elif tool == "write_file" and args.get("content"):
        extra.append(_code_preview(str(args.get("content", "")), _lang_for(str(args.get("path", "")))))
    else:                                                  # leitura/shell/etc.: preview da saída SEMPRE (paridade
        out = (e.get("out") or "").strip()                # Hermes — caixa de resultado por padrão), CURTA no
        if out:                                            # collapsed (3 linhas) e maior no expanded (12).
            prev = _out_preview(out, 12 if detail == "expanded" else 3)
            if prev is not None:
                extra.append(prev)
    return Group(line, *extra) if extra else line


def _out_preview(out: str, max_lines: int):
    """Preview indentado e dim da saída de uma tool (read/shell/…), capado em max_lines com marcador de
    truncamento — espelha a caixa de resultado do Hermes. None se vazio."""
    from rich.markup import escape
    out = (out or "").strip()
    if not out:
        return None
    lines = out.splitlines()
    shown = lines[:max_lines]
    rows = [f"     [{MUTE}]{escape(ln)}[/]" for ln in shown]
    if len(lines) > max_lines:
        rows.append(f"     [{DIM}]… +{len(lines) - max_lines} linhas[/]")
    return Text.from_markup("\n".join(rows))


class InputHistory:
    """Anel de histórico do input (↑/↓ recall das mensagens enviadas) — paridade Hermes (useInputHandlers).
    Ignora vazios e dups consecutivas. `prev()` anda pro mais antigo, `next()` pro mais novo; passar do fim
    volta pra linha nova (vazia). Puro/testável; o TUI só liga as setas quando o menu de comandos está fechado."""

    def __init__(self, cap: int = 200):
        self._items: list[str] = []
        self._pos: int | None = None                       # None = na ponta "viva" (linha nova)
        self._cap = max(1, int(cap))

    def add(self, line: str) -> None:
        s = (line or "").strip()
        if s and (not self._items or self._items[-1] != s):
            self._items.append(s)
            del self._items[:-self._cap]                    # bounded
        self._pos = None                                    # toda submissão volta o cursor pra ponta

    def prev(self) -> str:
        if not self._items:
            return ""
        self._pos = len(self._items) - 1 if self._pos is None else max(0, self._pos - 1)
        return self._items[self._pos]

    def next(self) -> str:
        if self._pos is None:
            return ""
        self._pos += 1
        if self._pos >= len(self._items):
            self._pos = None
            return ""
        return self._items[self._pos]


def fmt_elapsed(seconds) -> str:
    """Duração humana e compacta (paridade StatusRule do Hermes): '45s' · '1m 30s' · '1h 1m'. Nunca negativa."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


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
    t.append(f"  · {turns} {_tr('status.turns', _default='turns')}", style=MUTE)
    if elapsed:
        t.append(f"  · ⏱ {elapsed:.0f}s", style=MUTE)
    return t


def command_matches(typed: str, *, limit: int = 60):
    """[(label, name)] dos slash commands (chat) que casam com o digitado depois de '/'. [] = nenhum.
    `label` é um Text bonito (/nome args — descrição); `name` é o nome canônico p/ completar o input.
    limit alto DE PROPÓSITO: digitar '/' tem que listar TODOS (o menu rola); o usuário não decora os nomes."""
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
