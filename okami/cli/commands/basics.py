"""Comandos básicos: run · providers · doctor · login · gate."""
from __future__ import annotations

import platform
import sys

import typer
from rich.table import Table
from okami import __version__
from okami.llm import providers as prov
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _ping_models,
)


@app.command()
def run(
    prompt: str = typer.Argument(..., help="Prompt para o agente."),
    provider: str = typer.Option(None, "--provider", "-p", help="Nome do provider (default: do okami.yaml)."),
    model: str = typer.Option(None, "--model", "-m", help="Sobrescreve o model do provider."),
    system: str = typer.Option(None, "--system", "-s", help="System prompt opcional."),
    no_stream: bool = typer.Option(False, "--no-stream", help="Desliga streaming."),
) -> None:
    """Faz uma ida-e-volta ao provider (Fase 0)."""
    cfg = _load()
    try:
        pc = cfg.provider(provider)
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(
        f"[dim]provider=[/dim][bold]{pc.name}[/bold] "
        f"[dim]model=[/dim]{model or pc.model} [dim]tier=[/dim]{pc.tier}"
    )
    if not pc.ready:
        console.print(
            f"[yellow]Aviso:[/yellow] provider '{pc.name}' sem chave "
            f"(defina {pc.api_key_env}). Tentando mesmo assim..."
        )

    try:
        if no_stream:
            out = prov.complete(cfg, prompt, provider=provider, system=system, model=model)
            console.print(out)
        else:
            for piece in prov.stream_complete(
                cfg, prompt, provider=provider, system=system, model=model
            ):
                sys.stdout.write(piece)
                sys.stdout.flush()
            sys.stdout.write("\n")
    except Exception as e:  # noqa: BLE001
        console.print(f"\n[red]Erro na chamada:[/red] {e}")
        raise typer.Exit(1)


@app.command("providers")
def list_providers() -> None:
    """Lista os providers configurados e se estão prontos."""
    cfg = _load()
    table = Table(title="Okami providers")
    table.add_column("nome", style="bold")
    table.add_column("tier")
    table.add_column("model")
    table.add_column("api_base")
    table.add_column("pronto?")
    for name, pc in cfg.providers.items():
        flag = "[green]sim[/green]" if pc.ready else "[yellow]falta chave[/yellow]"
        default_mark = " [cyan](default)[/cyan]" if name == cfg.default_provider else ""
        table.add_row(name + default_mark, pc.tier, pc.model, pc.api_base or "-", flag)
    console.print(table)


@app.command()
def doctor(
    fix: bool = typer.Option(False, "--fix", help="Conserta o que dá: lock órfão, perms do .env, temp."),
    json_out: bool = typer.Option(False, "--json", help="Saída em JSON estruturado (monitoramento/CI)."),
    lint: bool = typer.Option(False, "--lint", help="Lint de POSTURA (segurança/exposição), estilo OpenClaw."),
) -> None:
    """Diagnostica config, chaves e conectividade. `--fix` repara; `--json` p/ máquina; `--lint` postura."""
    if lint:                                        # conformance/postura (#12): pass/warn/fail
        from okami.core.lint import lint_posture, summarize
        findings = lint_posture(_load())
        if json_out:
            import json as _json
            payload = {"summary": summarize(findings),
                       "findings": [vars(x) for x in findings]}
            console.print_json(_json.dumps(payload, ensure_ascii=False))
            raise typer.Exit(0 if payload["summary"]["ok"] else 1)
        icon = {"pass": "[green]✓[/green]", "warn": "[yellow]⚠[/yellow]", "fail": "[red]✗[/red]"}
        console.print("[bold]Okami[/bold] — lint de postura\n")
        for x in findings:
            console.print(f"{icon.get(x.level, '?')} [bold]{x.check}[/bold]: {x.message}"
                          + (f"\n   [dim]→ {x.fix}[/dim]" if x.fix and x.level != "pass" else ""))
        s = summarize(findings)
        console.print(f"\n[dim]{s['counts']['pass']} ok · {s['counts']['warn']} avisos · "
                      f"{s['counts']['fail']} falhas[/dim]")
        raise typer.Exit(0 if s["ok"] else 1)
    if json_out:                                    # caminho máquina: relatório estruturado + health
        import json as _json

        from okami.core.doctor import build_report, health_ok
        rep = build_report(_load(), ping=_ping_models)
        rep["healthy"] = health_ok(rep)
        console.print_json(_json.dumps(rep, ensure_ascii=False))
        raise typer.Exit(0 if rep["healthy"] else 1)
    import shutil
    import sqlite3
    import stat as _stat

    from rich.text import Text

    from okami.cli import _ui
    cfg = _load()
    console.print()
    console.print(_ui.header("doctor",
                             f"v{__version__} · {platform.system()} {platform.release()} · Python {platform.python_version()}"))
    console.print()

    # --- providers (auth + endpoint) ---
    pt = _ui.data_table(
        ("", {"width": 2, "no_wrap": True}),
        ("provider", {"style": f"bold {_ui.FG}", "no_wrap": True}),
        ("transporte", {"style": _ui.MUTE, "no_wrap": True}),
        ("auth", {"no_wrap": True}),
        ("endpoint", {"style": _ui.MUTE, "overflow": "ellipsis", "no_wrap": True, "max_width": 46}),
        title="providers",
    )
    for name, pc in cfg.providers.items():
        mark = Text("★", style=_ui.ORANGE) if name == cfg.default_provider else Text(" ")
        if pc.transport in ("codex_oauth", "minimax_oauth"):
            auth = _ui.badge("ready", "logado") if pc.ready else _ui.badge("missing", f"okami login {name}")
        elif pc.transport == "claude_cli":
            auth = _ui.badge("ready", "CLI claude") if pc.ready else _ui.badge("missing", "instale o CLI")
        elif pc.api_key_env:
            auth = _ui.badge("ready", pc.api_key_env) if pc.resolved_key() else _ui.badge("missing", f"def {pc.api_key_env}")
        elif pc.api_key:
            auth = _ui.badge("ok", "literal/dummy")
        else:
            auth = _ui.badge("off", "nenhuma")
        ep = Text("—", style=_ui.DIM)
        if pc.api_base:
            ok, msg = _ping_models(pc.api_base)
            host = pc.api_base.replace("https://", "").replace("http://", "")
            ep = Text()
            ep.append_text(_ui.dot("ok" if ok else "fail"))
            ep.append(f"  {host} · {msg[:34]}", style=_ui.MUTE)
        pt.add_row(mark, name, pc.transport, auth, ep)
    console.print(pt)
    console.print()

    # --- memória ---
    mem = cfg.memory or {}
    emb = mem.get("embedder") or {}
    emb_v = Text("desligado", style=_ui.MUTE)
    if emb.get("enabled", True) and emb.get("model"):
        from okami.memory import OpenAICompatEmbedder
        ok = OpenAICompatEmbedder(emb.get("api_base", "http://localhost:1234/v1"), emb["model"]).available()
        emb_v = _ui.badge("ok", emb.get("api_base", "")) if ok else _ui.badge("warn", "offline → BM25")
    fl = mem.get("files", {})
    mem_rows = [
        ("backend", Text(mem.get("backend", "sqlite-fts5"), style=_ui.FG)),
        ("embedder", emb_v),
        ("honcho", Text((mem.get("honcho") or {}).get("base_url", "—"), style=_ui.SOFT)),
        ("arquivos .md", Text("SOUL · VOICE · PERSONA · AGENTS · USER · MEMORY", style=_ui.SOFT)),
        ("limites (chars)", Text(f"soul {fl.get('soul', 6000)} · voice {fl.get('voice', 6000)} · "
                                 f"persona {fl.get('persona', 6000)} · user {fl.get('user', 4000)}", style=_ui.MUTE)),
    ]
    console.print(_ui.card(_ui.kv(mem_rows), title="memória", accent=_ui.CYAN))

    # --- ambiente / toolchain ---
    tools_line = Text()
    for tool in ("git", "uv", "node", "docker", "claude", "rg"):
        path = shutil.which(tool)
        tools_line.append_text(_ui.dot("ok" if path else "off"))
        tools_line.append(f" {tool}   ", style=_ui.SOFT if path else _ui.MUTE)
    try:
        _c = sqlite3.connect(":memory:")
        _c.execute("CREATE VIRTUAL TABLE _t USING fts5(x)")
        _c.close()
        fts_ok = True
    except sqlite3.Error:
        fts_ok = False
    codex_auth = ((Path.home() / ".codex" / "auth.json").exists()
                  or (Path.home() / ".okami" / "credentials" / "codex.json").exists())
    from okami.config import global_env_path
    genv = global_env_path()
    if genv.exists():
        mode = _stat.S_IMODE(genv.stat().st_mode)
        env_v = _ui.badge("ok", "0600") if mode == 0o600 else _ui.badge("warn", f"{oct(mode)[2:]} → use 0600")
    else:
        env_v = Text("nenhum (okami config set …)", style=_ui.MUTE)
    from okami.core.sandbox import SandboxPolicy
    sb = SandboxPolicy.from_config(getattr(cfg, "sandbox", {}) or {})
    sb_v = Text()
    sb_v.append(f"{sb.backend} · {sb.mode} · net {'on' if sb.network_on else 'off'}   ", style=_ui.FG)
    sb_v.append_text(_ui.badge("ok", "isolamento real") if sb.backend == "docker"
                     else _ui.badge("warn", "cercas locais"))
    from okami.integrations.mcp import servers_of
    srv = servers_of(getattr(cfg, "mcp", None))
    env_rows = [
        ("toolchain", tools_line),
        ("SQLite FTS5", _ui.badge("ok", "híbrida") if fts_ok else _ui.badge("warn", "LIKE (sem FTS5)")),
        ("codex auth", _ui.badge("ok", "logado") if codex_auth else _ui.badge("missing", "okami login codex")),
        (".env global", env_v),
        ("MCP", Text(f"{len(srv)} servidor(es): {', '.join(list(srv)[:6])}" if srv else "nenhum",
                     style=_ui.SOFT if srv else _ui.MUTE)),
        ("sandbox", sb_v),
    ]
    console.print(_ui.card(_ui.kv(env_rows), title="ambiente", accent=_ui.MAGENTA))

    if fix:
        from okami.config import global_env_path
        from okami.core.maintenance import clean_stale_locks, fix_env_perms, prune_temp
        console.print("\n[bold]--fix[/bold]")
        locks = clean_stale_locks(".")
        env_fixed = fix_env_perms(global_env_path())
        rm_t, freed = prune_temp(".")
        console.print(f"  locks órfãos removidos: [bold]{len(locks)}[/bold]")
        console.print(f"  ~/.okami/.env perms: {'[yellow]corrigido → 0600[/yellow]' if env_fixed else '[green]ok[/green]'}")
        console.print(f"  temporários removidos: [bold]{len(rm_t)}[/bold] [dim]({freed / 1024:.1f} KB)[/dim]")


@app.command()
def login(
    provider: str = typer.Argument(..., help="Provider para autenticar (ex.: codex, minimax)."),
) -> None:
    """Autentica um provider de assinatura (device flow / CLI oficial)."""
    from okami.llm import oauth

    cfg = _load()
    try:
        pc = cfg.provider(provider)
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if pc.transport == "codex_oauth":  # device flow NATIVO da OpenAI (sem codex CLI)
        try:
            oauth.codex_device_login(lambda m: console.print(m))
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Falha no login:[/red] {e}")
            raise typer.Exit(1)
        console.print(f"[green]✓ login '{provider}' concluído[/green]")
        return

    if pc.login_cmd:  # delega ao CLI oficial (fallback opcional)
        console.print(f"[dim]delegando para:[/dim] {' '.join(pc.login_cmd)}")
        try:
            rc = oauth.cli_delegate_login(pc.login_cmd)
        except FileNotFoundError:
            console.print(f"[red]CLI '{pc.login_cmd[0]}' não encontrado.[/red] Instale-o e tente de novo.")
            raise typer.Exit(1)
        raise typer.Exit(rc)

    if pc.oauth:  # device flow nativo genérico (MiniMax)
        try:
            oauth.device_login(provider, pc.oauth, lambda m: console.print(m))
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Falha no login:[/red] {e}")
            raise typer.Exit(1)
        console.print(f"[green]✓ login '{provider}' concluído[/green]")
        return

    console.print(f"[yellow]'{provider}' não tem fluxo de login.[/yellow] Use .env/api_key.")


@app.command()
def gate(
    path: str = typer.Argument(".", help="Diretório a verificar."),
    contract: str = typer.Option("ui", "--contract", "-c", help="Nome do contrato em okami.yaml."),
) -> None:
    """Roda o verification gate de design (§4.3) sobre um diretório."""
    from okami.contracts import check_ui

    cfg = _load()
    spec = cfg.contracts.get(contract)
    if not spec:
        console.print(f"[red]Contrato '{contract}' não existe em okami.yaml[/red]")
        raise typer.Exit(1)
    viols = check_ui(Path(path), spec)
    if not viols:
        console.print(f"[green]✓ gate '{contract}' passou[/green] em {path}")
        return
    console.print(f"[red]✗ {len(viols)} violações[/red] (contrato '{contract}'):")
    for v in viols:
        console.print(f"  {v}")
    raise typer.Exit(1)


