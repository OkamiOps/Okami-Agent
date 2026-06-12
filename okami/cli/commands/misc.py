"""Status, tools, clean, help e version (+ callback raiz). auth/policy/observability têm módulos próprios."""
from __future__ import annotations

import typer
from okami.i18n import t as _tr
from rich.table import Table
from okami import __version__
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import _load
from okami.i18n import t


@app.command(help=_tr("cli.insights", _default="Cross-session usage analytics (tokens by day/model/platform)."))
def insights(
    days: int = typer.Option(30, "--days", "-d", help=_tr("cli.insights.days", _default="Window in days (default 30).")),
    workspace: str = typer.Option(".", "-w", "--workspace"),
    json_out: bool = typer.Option(False, "--json", help=_tr("cli.insights.json", _default="Structured JSON (scripts/monitoring).")),
) -> None:
    """Analytics de uso entre sessões: tokens por dia/modelo/plataforma, dos últimos N dias."""
    from okami.observability import insights as _ins
    rep = _ins.collect(workspace, days=days)
    if json_out:
        import json as _json
        console.print_json(_json.dumps(rep, ensure_ascii=False))
        return
    console.print(_ins.render(rep))


@app.command("serve-mcp", help=_tr("cli.serve_mcp", _default="Serve Okami as an MCP server (sessions/history/memory) over stdio."))
def serve_mcp(
    agent: str = typer.Option("okami", "-a", "--agent", help=_tr("cli.serve_mcp.agent", _default="Agent whose home/sessions to expose.")),
) -> None:
    """Serve o Okami como servidor MCP (sessões/histórico/memória) via stdio — p/ Claude Code/Cursor."""
    from okami.home import okami_home
    from okami.integrations.mcp_serve import OkamiMcpServer
    cfg = None
    try:
        cfg = _load()
    except Exception:  # noqa: BLE001 — serve mesmo sem config completa
        pass
    home = okami_home()                              # default: casa global (onde moram as sessões)
    try:
        from okami.agents import load_agents
        spec = load_agents().get(agent)
        if spec:
            home = spec.dir
    except Exception:  # noqa: BLE001 — sem spec → usa a casa global
        pass
    OkamiMcpServer(home, cfg=cfg).serve_stdio()


@app.command(help=_tr("cli.clean", _default="Disk cleanup: orphan locks + temp + audio + finished processes."))
def clean(
    workspace: str = typer.Option(".", "-w", "--workspace"),
    lock_stale: float = typer.Option(300.0, "--lock-stale", help=_tr("cli.clean.lock_stale", _default="Age (s) to consider a .lock orphaned.")),
    deep: bool = typer.Option(False, "--deep", help=_tr("cli.clean.deep", _default="Apply the declared RETENTION (sessions/checkpoints/tool_outputs).")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_tr("cli.clean.dry_run", _default="Only SHOW what would be removed (delete nothing).")),
    json_out: bool = typer.Option(False, "--json", help=_tr("cli.clean.json", _default="Per-area report in JSON (cron/monitoring).")),
) -> None:
    """Faxina de disco: lock órfão + temp + áudio + processos terminados. `--deep` aplica a quota
    versionada (bloco `retention:` do okami.yaml); `--dry-run` lista sem apagar; `--json` p/ máquina."""
    from okami.core.maintenance import fmt_bytes, run_clean
    ret = None
    try:                                              # retenção versionada (best-effort: sem config → defaults)
        ret = (_load().retention or None)
    except Exception:  # noqa: BLE001
        pass
    rep = run_clean(workspace, lock_stale=lock_stale, deep=deep, retention=ret, dry_run=dry_run)
    if json_out:
        import json as _json
        console.print_json(_json.dumps(rep, ensure_ascii=False))
        return
    from rich.text import Text

    from okami.cli import _ui
    verb = "seria removido" if dry_run else "removido"
    tag = _ui.badge("warn", "dry-run") if dry_run else _ui.badge("ok", "faxina")
    console.print()
    head = Text("  ")
    head.append_text(tag)
    head.append(f"   {workspace}" + (" · --deep (quota)" if deep else ""), style=_ui.MUTE)
    console.print(head)
    t = _ui.data_table(("área", {"style": f"bold {_ui.FG}", "no_wrap": True}),
                       ("itens", {"justify": "right", "style": _ui.SOFT}),
                       ("espaço", {"justify": "right", "style": _ui.MAGENTA}))
    for area, a in rep["areas"].items():
        if a["removed"] or a["bytes"]:
            t.add_row(area, str(a["removed"]), fmt_bytes(a["bytes"]) if a["bytes"] else "—")
    if rep["items_removed"]:
        console.print(t)
    console.print(_ui.fields([("total", Text(f"{rep['items_removed']} item(ns) {verb} · "
                                            f"{fmt_bytes(rep['bytes_freed'])}", style=_ui.FG))], label_w=8))
    if not deep:
        console.print(_ui.hint("okami clean --deep aplica a quota de sessions/checkpoints/tool_outputs"))
    console.print()


@app.command(help=_tr("cli.tools", _default="List the agent's tools (category · tier · sensitivity) — declarative registry."))
def tools() -> None:
    """Lista as ferramentas do agente (categoria · tier · sensibilidade) — registro declarativo (#14)."""

    from okami.cli import _ui
    from okami.core.tool_registry import by_category, missing
    from okami.core.tools import default_registry
    names = set(default_registry())
    console.print()
    console.print(_ui.masthead(__version__, right=f"{len(names)} ferramentas"))
    console.print()
    t = _ui.data_table(
        ("ferramenta", {"style": f"bold {_ui.MAGENTA}", "no_wrap": True}),
        ("categoria", {"style": _ui.MUTE, "no_wrap": True}),
        ("tier", {"style": _ui.MUTE, "no_wrap": True}),
        ("sensibilidade", {"no_wrap": True}),
    )
    _state = {"safe": "ok", "sensitive": "warn", "dangerous": "fail"}
    cats = by_category(names)
    for ci, (cat, specs) in enumerate(cats.items()):
        if ci:
            t.add_row("", "", "", "")                 # respiro entre categorias
        for s in specs:
            t.add_row(s.name, cat, s.tier, _ui.badge(_state.get(s.danger, "dim"), s.danger))
    console.print(_ui.panel(t, title="Ferramentas por categoria", accent=_ui.MAGENTA))
    drift = missing(names)
    if drift:
        console.print(f"[yellow]⚠ sem metadata no registry:[/yellow] {', '.join(drift)}")
    console.print(_ui.footer("Por superfície:", [
        ("okami status", "vê a postura de canais & sandbox"),
        ("okami doctor --lint", "lint de exposição (quem roda o quê)"),
    ]))
    console.print()


@app.command(help=_tr("cli.status", _default="Resolved view (hermes/openclaw-style status): agent, model, providers, memory, toggles."))
def status(
    json_out: bool = typer.Option(False, "--json", help=_tr("cli.status.json", _default="Structured JSON output (monitoring/CI).")),
) -> None:
    """Visão resolvida (estilo hermes/openclaw status): agente, modelo, providers, memória, toggles."""
    try:
        cfg = _load()
    except Exception as e:  # noqa: BLE001
        if json_out:
            console.print_json(data={"ok": False, "error": str(e)})
            raise typer.Exit(1)
        console.print(f"[red]config não carrega:[/red] {e}")
        raise typer.Exit(1)
    if json_out:                                      # caminho máquina (#12): status resolvido p/ monitoramento
        from okami.cli._shared import _collect_channels
        from okami.core.lint import lint_posture, summarize
        from okami.core.maintenance import disk_report
        from okami.integrations.mcp import servers_of
        pc = cfg.provider()
        _, _channels = _collect_channels()
        payload = {
            "ok": True,
            "default_provider": cfg.default_provider,
            "model": pc.model,
            "provider_ready": bool(pc.ready),
            "approvals_mode": (cfg.approvals or {}).get("mode", "manual"),
            "memory_backend": (cfg.memory or {}).get("backend", "sqlite-fts5"),
            "sandbox": (cfg.sandbox or {}),
            "channels": sorted((cfg.gateway or {}).keys()),
            "mcp_servers": sorted(servers_of(cfg.mcp)),   # #P1: mcp.servers.<n>, não a chave 'servers'
            "lint": summarize(lint_posture(cfg, channels=_channels)),
            "disk": disk_report(".", retention=cfg.retention),   # uso por área + quota (gateway long-running)
        }
        import json as _json
        console.print_json(_json.dumps(payload, ensure_ascii=False))
        raise typer.Exit(0)
    import os as _os

    from rich.text import Text

    from okami import __version__
    from okami.cli import _ui
    from okami.cli._shared import _collect_channels, _disk_renderable
    default_agent = (cfg.agents or {}).get("default", "—")
    pc = cfg.provider()
    appr = (cfg.approvals or {}).get("mode", "manual")
    persona_on = (cfg.persona or {}).get("observe", True)
    learn = cfg.learning or {}
    voice_on = bool((cfg.voice or {}).get("stt") or (cfg.voice or {}).get("tts"))
    think = pc.reasoning_effort or "—"
    from okami.core.lint import lint_posture, summarize
    raw, channels = _collect_channels()                  # canais (global + por-agente) p/ exposição consistente
    cs = summarize(lint_posture(cfg, channels=channels))
    cc = cs["counts"]

    # masthead: estado-resumo à direita (conforme / N falhas) -------------------
    right = ("● " + t("status.all_conformant", _default="all conformant") if cs["ok"]
             else "✗ " + t("status.conformance_fail", _default="{n} conformance failure(s)", n=cc["fail"]))
    console.print()
    console.print(_ui.masthead(__version__, right=right))
    console.print()

    cards = []

    # ◆ Sessão -----------------------------------------------------------------
    model_v = Text(pc.model, style=f"bold {_ui.CYAN}", overflow="fold")
    model_v.append(f"\n{cfg.default_provider} · {pc.tier}", style=_ui.MUTE)
    toggles = Text()
    for lbl, on in ((t("status.persona", _default="persona"), persona_on),
                    (t("status.voice", _default="voice"), voice_on),
                    ("auto-skill", learn.get("auto_skill"))):
        toggles.append_text(_ui.dot("on" if on else "off"))
        toggles.append(f" {lbl}  ", style=_ui.SOFT if on else _ui.MUTE)
    cards.append(_ui.panel(_ui.fields([
        (t("status.agent", _default="agent"), Text(default_agent, style=f"bold {_ui.FG}")),
        (t("status.model", _default="model"), model_v),
        (t("status.reasoning", _default="reasoning"), think),
        (t("status.memory", _default="memory"), cfg.memory.get("backend", "sqlite-fts5")),
        (t("status.approval", _default="approval"), _ui.badge("ok" if appr in ("manual", "smart") else "warn", appr)),
        (t("status.features", _default="features"), toggles),
    ], label_w=11), title=t("status.card.session", _default="Session"), accent=_ui.ORANGE))

    # ◆ Providers --------------------------------------------------------------
    tbl = _ui.data_table(
        ("", {"width": 1, "no_wrap": True}),
        ("provider", {"style": f"bold {_ui.FG}", "no_wrap": True}),
        (t("status.col.model", _default="model"), {"style": _ui.SOFT, "overflow": "ellipsis", "max_width": 18}),
        (t("status.col.state", _default="state"), {"no_wrap": True}),
    )
    for name, p in cfg.providers.items():
        mark = Text("★", style=_ui.ORANGE) if name == cfg.default_provider else Text(" ")
        if p.experimental:
            state = _ui.badge("warn", t("status.experimental", _default="experimental"))
        else:
            state = (_ui.badge("ready", t("status.ready", _default="ready")) if p.ready
                     else _ui.badge("missing", t("status.missing_auth", _default="needs auth")))
        tbl.add_row(mark, name, p.model, state)
    cards.append(_ui.panel(tbl, title=f"Providers ({len(cfg.providers)})", accent=_ui.MAGENTA))

    # ◆ Canais & Gateway -------------------------------------------------------
    ch_rows = []                                          # raw, channels já coletados acima (lint consistente)
    for (owner, ctype), conf in (channels or {}).items():
        if conf.get("allow_all"):
            st = _ui.badge("warn", t("status.ingress_open", _default="ingress OPEN"))
        elif conf.get("allow_chats"):
            st = _ui.badge("ok", t("status.allowlist", _default="allowlist ({n})", n=len(conf["allow_chats"])))
        else:
            st = _ui.badge("off", "deny-by-default")
        ch_rows.append((ctype + ("" if owner == "(global)" else f"·{owner}"), st))
    if not ch_rows:
        ch_rows.append((t("status.channels", _default="channels"),
                        Text(t("status.no_channels", _default="none — local DM (okami chat)"), style=_ui.MUTE)))
    host = (cfg.gateway or {}).get("host", "127.0.0.1")
    api_tok = bool(_os.getenv("OKAMI_API_TOKEN"))
    api_v = Text()
    api_v.append_text(_ui.dot("ok" if (host in ("127.0.0.1", "localhost") or api_tok) else "warn"))
    api_v.append(f" {host} · token {'set' if api_tok else 'OFF'}", style=_ui.SOFT)
    ch_rows.append(("API", api_v))
    cards.append(_ui.panel(_ui.fields(ch_rows, label_w=14),
                           title=t("status.card.channels", _default="Channels & Gateway"), accent=_ui.CYAN))

    # ◆ MCP + Conformance ------------------------------------------------------
    from okami.integrations.mcp import _trust_of, servers_of
    srv = servers_of(cfg.mcp)
    cf = Text()
    cf.append_text(_ui.badge("ok", t("status.conformant", _default="conformant")) if cs["ok"]
                   else _ui.badge("fail", t("status.failures", _default="{n} failure(s)", n=cc["fail"])))
    cf.append("  " + t("status.ok_warn", _default="{p} ok · {w} warnings", p=cc["pass"], w=cc["warn"]), style=_ui.MUTE)
    mcp_rows = [("conformance", cf)]
    if srv:
        for n, c in srv.items():
            mcp_rows.append((f"mcp·{n}", Text(f"trust={_trust_of(c or {})}", style=_ui.SOFT)))
    else:
        mcp_rows.append(("mcp", Text(t("status.no_mcp", _default="no server"), style=_ui.MUTE)))
    cards.append(_ui.panel(_ui.fields(mcp_rows, label_w=14), title="MCP & Conformance", accent=_ui.ORANGE))

    # ◆ Disco (medidores) ------------------------------------------------------
    cards.append(_ui.panel(_disk_renderable(cfg, as_meters=True),
                           title=t("status.card.disk", _default="Disk"), accent=_ui.MAGENTA))

    # ◆ Uso (tokens/custo) -----------------------------------------------------
    try:
        from okami.gateway.sessions import TranscriptStore
        from okami.home import agents_dir
        from okami.llm.usage import estimate_cost, format_tokens, summarize_store
        ws = agents_dir() / default_agent if default_agent and default_agent != "—" else Path(".")
        u = summarize_store(TranscriptStore(ws).load_store())
        if u.total_tokens:
            cr = estimate_cost(u, transport=pc.transport, provider=cfg.default_provider, model=pc.model)
            usage = Text()
            usage.append(f"{format_tokens(u.input_tokens)} in", style=_ui.FG)
            usage.append(f" · {format_tokens(u.output_tokens)} out", style=_ui.SOFT)
            if u.cache_read_tokens:
                usage.append(f" · {format_tokens(u.cache_read_tokens)} cache", style=_ui.MUTE)
            usage.append("\n" + t("status.cost", _default="cost {label}", label=cr.label), style=_ui.MAGENTA)
            cards.append(_ui.panel(usage, title=t("status.card.usage", _default="Usage"), accent=_ui.CYAN))
    except Exception:  # noqa: BLE001
        pass

    console.print(_ui.grid(cards, width=console.width))
    console.print(_ui.footer(t("status.next_steps", _default="Next steps:"), [
        ("okami chat", t("status.step.chat", _default="chat in the terminal")),
        ("okami doctor", t("status.step.doctor", _default="config/keys/connectivity diagnosis")),
        ("okami policy check --strict", t("status.step.ga", _default="GA readiness")),
    ]))
    console.print()


# Grupos do `okami help` (visão geral amigável; cada item é um comando real).
_HELP_GROUPS = [
    ("Começar", [("setup", "assistente de configuração (menus de seta)"),
                 ("chat", "conversa no terminal (TUI)"),
                 ("status", "visão resolvida (agente, modelo, providers, toggles)"),
                 ("doctor", "diagnostica config, chaves e conectividade")]),
    ("Canais (Telegram)", [("channel add telegram <token>", "conecta o bot (jeito fácil, sem o wizard)"),
                           ("channel list", "mostra os canais e quem pode falar"),
                           ("pair list / approve <código>", "libera quem pediu acesso (deny-by-default)"),
                           ("gateway", "sobe os bots de Telegram")]),
    ("Config", [("config show", "config efetiva (segredos mascarados)"),
                ("config set <k> <v>", "muda um valor (segredo→.env, resto→local)"),
                ("config get <k>", "lê um valor"), ("config path", "onde ficam os arquivos"),
                ("fs home", "libera QUALQUER pasta em ~/ (Vídeos/Música/…); fs full = a máquina toda")]),
    ("Conversar / rodar", [("chat -q \"...\"", "uma pergunta e sai (script)"),
                           ("run \"...\"", "ida-e-volta crua ao provider"),
                           ("task \"...\"", "harness até concluir (com critérios -e)"),
                           ("room \"...\"", "brainstorm multi-agente (moderador)")]),
    ("Providers", [("provider add", "adiciona um modelo do catálogo"),
                   ("providers", "lista providers e prontidão"),
                   ("provider default <id>", "troca o default"),
                   ("login <id>", "autentica assinatura/OAuth")]),
    ("Agentes", [("agent new <id>", "cria um agente (workspace próprio)"),
                 ("agent list", "lista agentes"), ("route <origem>", "mostra o roteamento")]),
    ("Identidade / gosto", [("persona-evolve \"...\"", "molda VOICE/PERSONA"),
                            ("persona-log", "histórico de evolução"),
                            ("taste like/dislike", "ensina o gosto de design"),
                            ("tune", "stats por modelo (auto-tune)")]),
    ("Memória", [("memory add/search/list", "inspeciona a memória"),
                 ("setup memory", "troca o backend de memória")]),
    ("Automação", [("cron add/list", "agenda tarefas"), ("hooks", "lista event hooks"),
                   ("heartbeat", "uma batida do Paperclip")]),
    ("Skills / MCP", [("skills", "lista skills"), ("learn <fonte>", "instala skill (com scan)"),
                      ("scan <path>", "verifica risco de uma skill"), ("mcp", "tools de servidores MCP")]),
    ("Mídia / IDE", [("image \"...\"", "gera imagem (gpt-image-2)"),
                     ("say / transcribe", "TTS / STT"), ("acp", "servidor ACP p/ IDE")]),
]


@app.command("help", help=_tr("cli.help", _default="Friendly overview of the commands. Use `okami <command> --help` for details."))
def help_cmd() -> None:
    """Visão geral dos comandos (amigável). Use `okami <comando> --help` p/ detalhes."""
    from rich.panel import Panel

    console.print(Panel(f"[bold #ff7527]🐺 Okami Agent[/] [dim]v{__version__}[/]\n"
                        "[dim]agente de codificação confiável — multi-modelo, multi-agente, evolutivo[/dim]",
                        border_style="#ff7527"))
    for group, items in _HELP_GROUPS:
        t = Table(box=None, show_header=False, padding=(0, 2, 0, 0))
        t.add_column(style="bold #ff39d1", no_wrap=True)
        t.add_column(style="white")
        for cmd, desc in items:
            t.add_row(f"okami {cmd}", desc)
        console.print(f"[bold #ff7527]{group}[/]")
        console.print(t)
    console.print("[dim]começo rápido:[/dim] [bold]okami setup[/bold] [dim]→[/dim] [bold]okami chat[/bold]   "
                  "[dim]| Telegram:[/dim] [bold]okami channel add telegram <token> --allow-all[/bold] "
                  "[dim]→[/dim] [bold]okami gateway[/bold]")
    console.print("[dim]detalhe de um comando:[/dim] [bold]okami <comando> --help[/bold]")


@app.command(help=_tr("cli.version", _default="Show the version."))
def version() -> None:
    """Mostra a versão."""
    console.print(__version__)


def _version_cb(value: bool) -> None:
    if value:
        console.print(__version__)
        raise typer.Exit()


@app.callback(invoke_without_command=True,
              help=_tr("cli.root", _default="Okami Agent — CLI. With no command, shows the overview."))
def _root(
    ctx: typer.Context,
    _version: bool = typer.Option(False, "--version", "-V", help=_tr("cli.root.version", _default="Show the version and exit."),
                                  callback=_version_cb, is_eager=True),
    lang: str = typer.Option(None, "--lang", help=_tr("cli.root.lang", _default="Language: en | pt (default: en; or OKAMI_LANG / config lang:).")),
) -> None:
    """Okami Agent — CLI. Sem comando, mostra a visão geral."""
    if lang:                                          # --lang vence env/config nesta invocação
        from okami.i18n import set_lang
        set_lang(lang)
    try:                                              # migra ~/skills e ~/agents soltos → ~/.okami (1×, idempotente)
        import sys as _sys

        from okami.home import migrate_stray, skills_dir
        migrate_stray(emit=lambda m: print(m, file=_sys.stderr))   # stderr: não polui --json na 1ª vez
        from okami.skills import tidy_skill_names      # P0: nome de skill gigante (auto-distill antigo) → canônico
        tidy_skill_names(skills_dir(), emit=lambda m: print(m, file=_sys.stderr))
    except Exception:  # noqa: BLE001 — migração nunca derruba um comando
        pass
    if ctx.invoked_subcommand is None:
        help_cmd()


if __name__ == "__main__":
    app()
