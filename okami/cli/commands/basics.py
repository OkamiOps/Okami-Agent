"""Comandos básicos: run · providers · doctor · login · gate."""
from __future__ import annotations

import platform
import sys

import typer
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
def list_providers(
    json_out: bool = typer.Option(False, "--json", help="Saída em JSON estruturado (scripts/CI)."),
) -> None:
    """Lista os providers configurados e se estão prontos (★ = default)."""
    cfg = _load()
    if json_out:
        import json as _json
        payload = {"default_provider": cfg.default_provider, "providers": {
            name: {"model": pc.model, "tier": pc.tier, "transport": pc.transport,
                   "api_base": pc.api_base or None, "ready": bool(pc.ready)}
            for name, pc in cfg.providers.items()}}
        console.print_json(_json.dumps(payload, ensure_ascii=False))
        return
    from rich.text import Text

    from okami.cli import _ui
    console.print()
    console.print(_ui.masthead(__version__, right="providers"))
    console.print()
    t = _ui.data_table(
        ("", {"width": 1, "no_wrap": True}),
        ("provider", {"style": f"bold {_ui.FG}", "no_wrap": True}),
        ("modelo", {"style": _ui.SOFT}),
        ("tier", {"style": _ui.MUTE, "no_wrap": True}),
        ("transporte", {"style": _ui.MUTE, "no_wrap": True}),
        ("estado", {"no_wrap": True}),
    )
    for name, pc in cfg.providers.items():
        mark = Text("★", style=_ui.ORANGE) if name == cfg.default_provider else Text(" ")
        state = _ui.badge("ready", "pronto") if pc.ready else _ui.badge("missing", "falta auth")
        t.add_row(mark, name, pc.model, pc.tier, pc.transport, state)
    console.print(_ui.panel(t, title=f"Providers ({len(cfg.providers)})",
                            subtitle="★ default", accent=_ui.MAGENTA))
    console.print(_ui.footer("Próximos passos:", [
        ("okami provider add", "adiciona um modelo do catálogo (23 presets)"),
        ("okami provider default <id>", "troca o provider padrão"),
        ("okami login <id>", "autentica assinatura/OAuth"),
    ]))
    console.print()


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
    from okami.cli._shared import _disk_renderable
    cfg = _load()
    sysinfo = f"{platform.system()} {platform.release()} · Python {platform.python_version()}"
    console.print()
    console.print(_ui.masthead(__version__, right=sysinfo))
    console.print()
    cards = []

    # ◆ Providers (auth + endpoint ping) ---------------------------------------
    pt = _ui.data_table(
        ("", {"width": 1, "no_wrap": True}),
        ("provider", {"style": f"bold {_ui.FG}", "no_wrap": True}),
        ("auth", {"no_wrap": True}),
        ("endpoint", {"style": _ui.MUTE, "overflow": "ellipsis", "no_wrap": True, "max_width": 30}),
    )
    for name, pc in cfg.providers.items():
        mark = Text("★", style=_ui.ORANGE) if name == cfg.default_provider else Text(" ")
        if pc.transport in ("codex_oauth", "minimax_oauth"):
            auth = _ui.badge("ready", "logado") if pc.ready else _ui.badge("missing", f"login {name}")
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
            ep.append(f" {host}", style=_ui.MUTE)
        pt.add_row(mark, name, auth, ep)
    cards.append(_ui.panel(pt, title=f"Providers ({len(cfg.providers)})", accent=_ui.MAGENTA))

    # ◆ Memória ----------------------------------------------------------------
    mem = cfg.memory or {}
    emb = mem.get("embedder") or {}
    emb_v = Text("desligado", style=_ui.MUTE)
    if emb.get("enabled", True) and emb.get("model"):
        from okami.memory import OpenAICompatEmbedder
        ok = OpenAICompatEmbedder(emb.get("api_base", "http://localhost:1234/v1"), emb["model"]).available()
        emb_v = _ui.badge("ok", "online") if ok else _ui.badge("warn", "offline → BM25")
    mem_rows = [
        ("backend", Text(mem.get("backend", "sqlite-fts5"), style=f"bold {_ui.FG}")),
        ("embedder", emb_v),
        ("honcho", Text((mem.get("honcho") or {}).get("base_url", "—"), style=_ui.SOFT)),
        ("arquivos", Text("SOUL · VOICE · PERSONA · USER · MEMORY", style=_ui.SOFT)),
    ]
    cards.append(_ui.panel(_ui.fields(mem_rows, label_w=10), title="Memória", accent=_ui.CYAN))

    # ◆ Ambiente / toolchain ---------------------------------------------------
    tools_line = Text()
    for tool in ("git", "uv", "node", "docker", "claude", "rg"):
        path = shutil.which(tool)
        tools_line.append_text(_ui.dot("ok" if path else "off"))
        tools_line.append(f" {tool}  ", style=_ui.SOFT if path else _ui.MUTE)
    try:
        _c = sqlite3.connect(":memory:")
        _c.execute("CREATE VIRTUAL TABLE _t USING fts5(x)")
        _c.close()
        fts_ok = True
    except sqlite3.Error:
        fts_ok = False
    from okami.home import read_path
    codex_auth = ((Path.home() / ".codex" / "auth.json").exists()
                  or read_path("credentials", "codex.json").exists())
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
    sb_v.append(f"{sb.backend}·{sb.mode} ", style=_ui.FG)
    sb_v.append_text(_ui.badge("ok", "isolado") if sb.backend == "docker"
                     else _ui.badge("warn", "cercas locais"))
    from okami.integrations.mcp import servers_of
    srv = servers_of(getattr(cfg, "mcp", None))
    env_rows = [
        ("toolchain", tools_line),
        ("SQLite FTS5", _ui.badge("ok", "híbrida") if fts_ok else _ui.badge("warn", "LIKE (sem FTS5)")),
        ("codex auth", _ui.badge("ok", "logado") if codex_auth else _ui.badge("missing", "okami login codex")),
        (".env global", env_v),
        ("MCP", Text(f"{len(srv)} servidor(es)" if srv else "nenhum", style=_ui.SOFT if srv else _ui.MUTE)),
        ("sandbox", sb_v),
    ]
    cards.append(_ui.panel(_ui.fields(env_rows, label_w=12), title="Ambiente", accent=_ui.ORANGE))

    # ◆ Disco (medidores) ------------------------------------------------------
    cards.append(_ui.panel(_disk_renderable(cfg, as_meters=True), title="Disco", accent=_ui.MAGENTA))

    console.print(_ui.grid(cards, width=console.width))
    console.print(_ui.footer("Próximos passos:", [
        ("okami doctor --lint", "lint de postura de segurança"),
        ("okami clean --deep --dry-run", "prévia da poda de disco (quota versionada)"),
        ("okami login <provider>", "autenticar provider de assinatura"),
    ]))
    console.print()

    if fix:
        from okami.config import global_env_path
        from okami.core.maintenance import clean_stale_locks, fix_env_perms, prune_temp
        console.print("\n[bold]--fix[/bold]")
        locks = clean_stale_locks(".")
        env_p = global_env_path()
        env_fixed = fix_env_perms(env_p)
        rm_t, freed = prune_temp(".")
        console.print(f"  locks órfãos removidos: [bold]{len(locks)}[/bold]")
        console.print(f"  {env_p} perms: {'[yellow]corrigido → 0600[/yellow]' if env_fixed else '[green]ok[/green]'}")
        console.print(f"  temporários removidos: [bold]{len(rm_t)}[/bold] [dim]({freed / 1024:.1f} KB)[/dim]")


@app.command()
def harden(
    off: bool = typer.Option(False, "--off", help="Desliga o isolamento estrito (volta ao dev-friendly)."),
) -> None:
    """Liga o ISOLAMENTO ESTRITO p/ exposição pública (#2): superfície exposta SEM Docker → run_shell/
    process DESABILITADOS, não degradam pro host. Grava sandbox.require_isolation no okami.local.yaml.

    Use ANTES de expor o gateway publicamente ('qualquer um manda mensagem'). CLI/dev local não muda."""

    from okami.core.safe_io import read_yaml_resilient, secure_write_yaml
    p = Path("okami.local.yaml")
    data = read_yaml_resilient(p, default={}) or {}
    sb = dict(data.get("sandbox") or {})
    if off:
        sb.pop("require_isolation", None)
    else:
        sb["require_isolation"] = True
    data["sandbox"] = sb
    secure_write_yaml(p, data)
    if off:
        console.print("[yellow]⚠ isolamento estrito DESLIGADO[/yellow] — superfície exposta volta a degradar "
                      "p/ local sem Docker (dev-friendly). NÃO recomendado p/ uso público.")
        return
    console.print("[green]✓ isolamento estrito LIGADO[/green] [dim](sandbox.require_isolation: true em "
                  "okami.local.yaml)[/dim]")
    from okami.core.sandbox import SandboxPolicy
    has_docker = SandboxPolicy.from_config({"backend": "auto"}).effective_backend() == "docker"
    if not has_docker:
        console.print("[yellow]   Docker NÃO detectado[/yellow] — em superfície exposta o run_shell/process "
                      "ficará DESABILITADO (fail-closed) até ter Docker. É o comportamento seguro p/ GA.")
    console.print("[dim]   Verifique: okami policy check --strict  ·  reverter: okami harden --off[/dim]")


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


