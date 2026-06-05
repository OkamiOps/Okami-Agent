"""Status, help e version (+ callback raiz)."""
from __future__ import annotations

import typer
from rich.table import Table
from okami import __version__
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _persona_ws,
)


auth_app = typer.Typer(invoke_without_command=True,
                       help="Perfis de AUTH (metadata, sem segredo): `okami auth` lista; `auth status --json`.")
app.add_typer(auth_app, name="auth")


@auth_app.callback(invoke_without_command=True)
def auth_main(ctx: typer.Context) -> None:
    """`okami auth` sem subcomando = lista os perfis de autenticação (tipo, status, onde mora)."""
    if ctx.invoked_subcommand is not None:
        return
    auth_list()


@auth_app.command("list")
def auth_list() -> None:
    """Lista os perfis de auth — tipo (oauth/cli/api_key), status, e ONDE mora a credencial (sem o valor)."""
    from okami.core.auth_profiles import build_auth_profiles
    profs = build_auth_profiles(_load())
    t = Table(title="perfis de auth", border_style="#3d3e50", header_style="bold #ff7527")
    for col in ("provider", "tipo", "tier", "assinatura", "status", "credencial (onde)"):
        t.add_column(col)
    sm = {"ready": "[green]ready[/green]", "missing": "[red]missing[/red]", "expired": "[yellow]expired[/yellow]"}
    for p in profs:
        star = " [bold #ff7527]★[/]" if p["default"] else ""
        t.add_row(p["name"] + star, p["kind"], p["tier"],
                  "✓" if p["subscription"] else "—", sm.get(p["status"], p["status"]), p["location"])
    console.print(t)
    console.print("[dim]★ = default_provider · assinatura ✓ = OAuth/CLI (nunca pay-as-you-go)[/dim]")


@auth_app.command("status")
def auth_status(json_out: bool = typer.Option(False, "--json", help="Saída JSON (monitoramento/CI).")) -> None:
    """Status dos perfis de auth (machine-readable com --json)."""
    from okami.core.auth_profiles import build_auth_profiles
    profs = build_auth_profiles(_load())
    if json_out:
        import json as _json
        console.print_json(_json.dumps({"profiles": profs}, ensure_ascii=False))
        raise typer.Exit(0 if all(p["status"] != "missing" or not p["default"] for p in profs) else 1)
    for p in profs:
        console.print(f"{p['name']}: {p['status']} ({p['kind']}, {p['location']})")


policy_app = typer.Typer(help="Conformance de POLÍTICA/postura (#12): `okami policy check` (CI/pre-deploy).")
app.add_typer(policy_app, name="policy")


@policy_app.command("check")
def policy_check(
    json_out: bool = typer.Option(False, "--json", help="Saída JSON (CI)."),
) -> None:
    """Valida a POSTURA (aprovação, segredo, sandbox, MCP trust, exposição). Exit≠0 se houver falha."""
    from okami.core.lint import lint_posture, summarize
    findings = lint_posture(_load())
    s = summarize(findings)
    if json_out:
        import json as _json
        console.print_json(_json.dumps({"summary": s, "findings": [vars(x) for x in findings]}, ensure_ascii=False))
        raise typer.Exit(0 if s["ok"] else 1)
    icon = {"pass": "[green]✓[/green]", "warn": "[yellow]⚠[/yellow]", "fail": "[red]✗[/red]"}
    for x in findings:
        if x.level != "pass":
            console.print(f"{icon[x.level]} [bold]{x.check}[/bold]: {x.message} [dim]→ {x.fix}[/dim]")
    verdict = "[green]✓ postura ok[/green]" if s["ok"] else f"[red]✗ {s['counts']['fail']} falha(s) de política[/red]"
    console.print(verdict)
    raise typer.Exit(0 if s["ok"] else 1)


@app.command()
def rollback(
    n: int = typer.Argument(1, help="Quantas escritas de arquivo reverter (da mais recente)."),
    agent: str = typer.Option(None, "-a", "--agent"),
    workspace: str = typer.Option(".", "-w", "--workspace"),
) -> None:
    """Desfaz as últimas N escritas de arquivo (checkpoints — rede de segurança estilo Hermes)."""
    from okami.gateway.checkpoints import Checkpoints

    reverted = Checkpoints(_persona_ws(agent, workspace)).rollback(n)
    if not reverted:
        console.print("[dim]nada para reverter.[/dim]")
        return
    for p in reverted:
        console.print(f"[yellow]revertido[/yellow] {p}")


@app.command()
def events(
    agent: str = typer.Option(None, "-a", "--agent"),
    workspace: str = typer.Option(".", "-w", "--workspace"),
    n: int = typer.Option(40, "-n", help="Quantos eventos finais mostrar."),
) -> None:
    """Timeline da última task (replay/debug) — .okami/events.jsonl."""
    import datetime as _dt

    from okami.observability.events import read_events
    ws = _persona_ws(agent, workspace)
    evs = read_events(ws)
    if not evs:
        console.print(f"[dim]sem eventos em {ws}/.okami/events.jsonl[/dim]")
        return
    for e in evs[-n:]:
        ts = e.get("ts")
        hhmm = _dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if isinstance(ts, (int, float)) else "--:--:--"
        extra = {k: v for k, v in e.items() if k not in ("seq", "ts", "type")}
        brief = "  ".join(f"[dim]{k}=[/dim]{str(v)[:60]}" for k, v in extra.items())
        console.print(f"[dim]{e.get('seq', '?'):>3} {hhmm}[/dim] [bold #ff7527]{e.get('type', '?')}[/bold #ff7527] {brief}")
    calls = [e for e in evs if e.get("type") == "llm_call"]      # resumo de usage por-chamada (P2)
    if calls:
        ti = sum(int(e.get("tokens_in", 0) or 0) for e in calls)
        to = sum(int(e.get("tokens_out", 0) or 0) for e in calls)
        traces = {e.get("trace") for e in evs if e.get("trace")}
        console.print(f"[dim]── {len(calls)} chamada(s) LLM · {ti:,} tok in · {to:,} tok out"
                      f"{f' · {len(traces)} turno(s)' if traces else ''} ──[/dim]")


@app.command()
def clean(
    workspace: str = typer.Option(".", "-w", "--workspace"),
    lock_stale: float = typer.Option(300.0, "--lock-stale", help="Idade (s) p/ considerar um .lock órfão."),
    deep: bool = typer.Option(False, "--deep", help="Também poda sessões arquivadas e checkpoints antigos (quota)."),
    days: float = typer.Option(30.0, "--days", help="Idade (dias) p/ podar no --deep."),
    keep: int = typer.Option(10, "--keep", help="Quantas sessões arquivadas manter (as mais recentes)."),
) -> None:
    """Faxina de disco (P2): lock órfão + temporários + áudio. `--deep` aplica quota a sessões/checkpoints."""
    from okami.core.maintenance import clean_workspace
    rep = clean_workspace(workspace, lock_stale=lock_stale)
    extra = ""
    if deep:
        from okami.core.maintenance import prune_checkpoints, prune_sessions
        rs, fs = prune_sessions(workspace, days=days, keep=keep)
        rc, fc = prune_checkpoints(workspace, days=days, keep=keep * 5)
        rep["bytes_freed"] += fs + fc
        extra = f", {len(rs)} sessão(ões) arquivada(s), {len(rc)} checkpoint(s)"
    kb = rep["bytes_freed"] / 1024
    console.print(f"[green]✓ faxina[/green] [dim]({workspace})[/dim]: "
                  f"{rep['locks_removed']} lock(s), {rep['temp_removed']} temp, {rep['audio_removed']} áudio{extra} "
                  f"[dim]· {kb:.1f} KB liberados[/dim]")


@app.command()
def tools() -> None:
    """Lista as ferramentas do agente (categoria · tier · sensibilidade) — registro declarativo (#14)."""
    from okami.core.tool_registry import by_category, missing
    from okami.core.tools import default_registry
    names = set(default_registry())
    t = Table(title="[bold #ff7527]Ferramentas do Okami[/]", box=None, padding=(0, 2, 0, 0))
    t.add_column("ferramenta", style="bold #ff39d1")
    t.add_column("categoria")
    t.add_column("tier")
    t.add_column("sensibilidade")
    _dc = {"safe": "green", "sensitive": "yellow", "dangerous": "red"}
    for cat, specs in by_category(names).items():
        for s in specs:
            t.add_row(s.name, cat, s.tier, f"[{_dc.get(s.danger, 'white')}]{s.danger}[/]")
    console.print(t)
    drift = missing(names)
    if drift:
        console.print(f"[yellow]⚠ sem metadata no registry:[/yellow] {', '.join(drift)}")


@app.command()
def status(
    json_out: bool = typer.Option(False, "--json", help="Saída em JSON estruturado (monitoramento/CI)."),
) -> None:
    """Visão resolvida (estilo hermes/openclaw status): agente, modelo, providers, memória, toggles."""
    from rich.panel import Panel
    from rich.table import Table as _T
    try:
        cfg = _load()
    except Exception as e:  # noqa: BLE001
        if json_out:
            console.print_json(data={"ok": False, "error": str(e)})
            raise typer.Exit(1)
        console.print(f"[red]config não carrega:[/red] {e}")
        raise typer.Exit(1)
    if json_out:                                      # caminho máquina (#12): status resolvido p/ monitoramento
        from okami.core.lint import lint_posture, summarize
        pc = cfg.provider()
        payload = {
            "ok": True,
            "default_provider": cfg.default_provider,
            "model": pc.model,
            "provider_ready": bool(pc.ready),
            "approvals_mode": (cfg.approvals or {}).get("mode", "manual"),
            "memory_backend": (cfg.memory or {}).get("backend", "sqlite-fts5"),
            "sandbox": (cfg.sandbox or {}),
            "channels": sorted((cfg.gateway or {}).keys()),
            "mcp_servers": sorted((cfg.mcp or {}).keys()),
            "lint": summarize(lint_posture(cfg)),
        }
        import json as _json
        console.print_json(_json.dumps(payload, ensure_ascii=False))
        raise typer.Exit(0)
    default_agent = (cfg.agents or {}).get("default", "—")
    pc = cfg.provider()
    appr = (cfg.approvals or {}).get("mode", "manual")
    persona_on = (cfg.persona or {}).get("observe", True)
    learn = cfg.learning or {}
    voice_on = bool((cfg.voice or {}).get("stt") or (cfg.voice or {}).get("tts"))
    think = pc.reasoning_effort or "—"
    body = (f"[bold #ff7527]agente[/] {default_agent}   "
            f"[bold #ff7527]modelo[/] {pc.model} [dim]({cfg.default_provider})[/dim]   "
            f"[dim]think[/] {think}\n"
            f"[dim]memória[/] {cfg.memory.get('backend', 'sqlite-fts5')}   "
            f"[dim]aprovação[/] {appr}   "
            f"[dim]persona[/] {'on' if persona_on else 'off'}   "
            f"[dim]voz[/] {'on' if voice_on else 'off'}   "
            f"[dim]auto-skill[/] {'on' if learn.get('auto_skill') else 'off'}")
    console.print(Panel(body, title="[bold #ff7527]Okami status[/]", border_style="#ff7527"))
    try:                                              # tokens/custo acumulados do agente default (§A5)
        from okami.gateway.sessions import TranscriptStore
        from okami.llm.usage import estimate_cost, format_tokens, summarize_store
        ws = Path("agents") / default_agent if default_agent and default_agent != "—" else Path(".")
        u = summarize_store(TranscriptStore(ws).load_store())
        if u.total_tokens:
            cr = estimate_cost(u, transport=pc.transport, provider=cfg.default_provider, model=pc.model)
            extra = f" · {format_tokens(u.cache_read_tokens)} cache" if u.cache_read_tokens else ""
            console.print(f"  [dim]tokens[/] {format_tokens(u.input_tokens)} in · "
                          f"{format_tokens(u.output_tokens)} out{extra}   [dim]custo[/] {cr.label}")
    except Exception:  # noqa: BLE001
        pass
    t = _T(title="Providers (auth)", border_style="#3d3e50")
    t.add_column("provider", style="bold")
    t.add_column("modelo")
    t.add_column("pronto?")
    for name, p in cfg.providers.items():
        flag = "[green]✓[/green]" if p.ready else "[yellow]falta auth[/yellow]"
        mark = name + (" [cyan](default)[/cyan]" if name == cfg.default_provider else "")
        t.add_row(mark, p.model, flag)
    console.print(t)


# Grupos do `okami help` (visão geral amigável; cada item é um comando real).
_HELP_GROUPS = [
    ("Começar", [("setup", "assistente de configuração (menus de seta)"),
                 ("chat", "conversa no terminal (TUI)"),
                 ("status", "visão resolvida (agente, modelo, providers, toggles)"),
                 ("doctor", "diagnostica config, chaves e conectividade")]),
    ("Config", [("config show", "config efetiva (segredos mascarados)"),
                ("config set <k> <v>", "muda um valor (segredo→.env, resto→local)"),
                ("config get <k>", "lê um valor"), ("config path", "onde ficam os arquivos")]),
    ("Conversar / rodar", [("chat -q \"...\"", "uma pergunta e sai (script)"),
                           ("run \"...\"", "ida-e-volta crua ao provider"),
                           ("task \"...\"", "harness até concluir (com critérios -e)"),
                           ("room \"...\"", "brainstorm multi-agente (moderador)"),
                           ("gateway", "sobe os bots de Telegram")]),
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


@app.command("help")
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
    console.print("[dim]dica: comece com[/dim] [bold]okami setup[/bold] [dim]e depois[/dim] [bold]okami chat[/bold]")


@app.command()
def version() -> None:
    """Mostra a versão."""
    console.print(__version__)


@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context) -> None:
    """Okami Agent — CLI. Sem comando, mostra a visão geral."""
    if ctx.invoked_subcommand is None:
        help_cmd()


if __name__ == "__main__":
    app()
