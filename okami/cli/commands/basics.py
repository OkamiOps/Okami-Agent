"""Comandos básicos: run · providers · doctor · login · gate."""
from __future__ import annotations

import json
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
    console.print(f"[bold]Okami[/bold] v{__version__} — doctor")
    console.print(
        f"[dim]{platform.system()} {platform.release()} · Python {platform.python_version()}[/dim]"
    )
    cfg = _load()
    console.print(f"default_provider: [bold]{cfg.default_provider}[/bold]\n")

    for name, pc in cfg.providers.items():
        console.print(f"[bold]{name}[/bold] ({pc.tier})")
        console.print(f"  model: {pc.model}")
        if pc.transport == "claude_cli":
            s = "[green]CLI 'claude' OK[/green]" if pc.ready else "[yellow]instale/logue o CLI 'claude'[/yellow]"
            console.print(f"  transport: claude_cli — {s}")
        elif pc.transport == "codex_oauth":
            s = "[green]~/.codex/auth.json OK[/green]" if pc.ready else f"[yellow]rode: okami login {name}[/yellow]"
            console.print(f"  transport: codex_oauth — {s}")
        elif pc.transport == "minimax_oauth":
            s = "[green]token OAuth OK[/green]" if pc.ready else f"[yellow]rode: okami login {name}[/yellow]"
            console.print(f"  transport: minimax_oauth — {s}")
        elif pc.api_key_env:
            mark = "[green]ok[/green]" if pc.resolved_key() else f"[yellow]definir {pc.api_key_env}[/yellow]"
            console.print(f"  chave: {mark}")
        elif pc.api_key:
            console.print("  chave: [green]literal/dummy[/green]")
        else:
            console.print("  chave: [dim]nenhuma[/dim]")
        if pc.api_base:
            ok, msg = _ping_models(pc.api_base)
            color = "green" if ok else "red"
            console.print(f"  endpoint {pc.api_base}: [{color}]{msg}[/{color}]")
        if pc.notes:
            console.print(f"  [dim]nota: {pc.notes}[/dim]")
        console.print()

    # --- memória (útil p/ setup distribuído via Tailscale) ---
    mem = cfg.memory or {}
    console.print(f"[bold]memória[/bold]: backend={mem.get('backend', 'sqlite-fts5')}")
    emb = mem.get("embedder") or {}
    if emb.get("enabled", True) and emb.get("model"):
        from okami.memory import OpenAICompatEmbedder
        e = OpenAICompatEmbedder(emb.get("api_base", "http://localhost:1234/v1"), emb["model"])
        ok = e.available()
        s = "[green]ok[/green]" if ok else "[yellow]offline → degrada p/ BM25[/yellow]"
        console.print(f"  embedder {emb.get('api_base')}: {s}")
    hc = mem.get("honcho")
    if hc:
        console.print(f"  honcho: {hc.get('base_url', '(base_url não definido)')}")
    fl = mem.get("files", {})
    console.print("  .md sempre injetados: identidade (SOUL/VOICE/PERSONA) + core (AGENTS/USER/MEMORY)")
    console.print(f"  limites (chars): soul={fl.get('soul', 6000)} voice={fl.get('voice', 6000)} "
                  f"persona={fl.get('persona', 6000)} agents={fl.get('agents', 4000)} "
                  f"user={fl.get('user', 4000)} memory={fl.get('memory', 4000)}")

    # --- toolchain & sistema (#13 self-review: doctor mais agressivo, estilo Hermes) ---
    import shutil
    import sqlite3
    import stat as _stat

    console.print("\n[bold]toolchain[/bold]")
    for tool, why in (("git", "skills/learn, checkpoints"), ("uv", "instalação/deps"),
                      ("node", "ACP/IDE e alguns MCP"), ("docker", "sandbox/serviços (opcional)"),
                      ("claude", "transporte claude_cli"), ("rg", "busca rápida (opcional)")):
        path = shutil.which(tool)
        console.print(f"  {tool}: {f'[green]{path}[/green]' if path else '[yellow]não encontrado[/yellow]'} "
                      f"[dim]({why})[/dim]")
    try:                                              # SQLite FTS5 → memória híbrida (senão degrada p/ LIKE)
        _c = sqlite3.connect(":memory:")
        _c.execute("CREATE VIRTUAL TABLE _t USING fts5(x)")
        _c.close()
        fts_ok = True
    except sqlite3.Error:
        fts_ok = False
    console.print(f"  SQLite FTS5: {'[green]ok[/green]' if fts_ok else '[yellow]ausente → memória usa LIKE[/yellow]'}")

    codex_auth = (Path.home() / ".codex" / "auth.json").exists() or \
        (Path.home() / ".okami" / "credentials" / "codex.json").exists()
    console.print(f"  codex auth: {'[green]logado[/green]' if codex_auth else '[yellow]rode: okami login codex[/yellow]'}")

    from okami.config import global_env_path
    genv = global_env_path()
    if genv.exists():
        mode = _stat.S_IMODE(genv.stat().st_mode)
        s = "[green](0600 ✓)[/green]" if mode == 0o600 else "[yellow](recomendado 0600)[/yellow]"
        console.print(f"  ~/.okami/.env: existe · perm {oct(mode)} {s}")
    else:
        console.print("  ~/.okami/.env: [dim]nenhum (configure com `okami config set`)[/dim]")

    mcp = getattr(cfg, "mcp", None) or {}
    if mcp:
        console.print(f"  MCP: {len(mcp)} servidor(es): {', '.join(list(mcp)[:6])}")
    else:
        console.print("  MCP: [dim]nenhum servidor configurado[/dim]")

    from okami.core.sandbox import SandboxPolicy
    sb = SandboxPolicy.from_config(getattr(cfg, "sandbox", {}) or {})
    real = ("[green]isolamento real[/green]" if sb.backend == "docker"
            else "[yellow]cercas locais (sem confinar FS/rede)[/yellow]")
    console.print(f"  sandbox: backend={sb.backend} · mode={sb.mode} · net={'on' if sb.network_on else 'off'} "
                  f"· timeout={sb.timeout}s — {real}")

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


