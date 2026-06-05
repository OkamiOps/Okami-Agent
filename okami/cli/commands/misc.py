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
def status() -> None:
    """Visão resolvida (estilo hermes/openclaw status): agente, modelo, providers, memória, toggles."""
    from rich.panel import Panel
    from rich.table import Table as _T
    try:
        cfg = _load()
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]config não carrega:[/red] {e}")
        raise typer.Exit(1)
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
