"""Comandos básicos: run · providers · doctor · login · gate."""
from __future__ import annotations

import platform
import sys

import typer
from okami.i18n import t as _tr
from okami import __version__
from okami.llm import providers as prov
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _ping_models,
)
from okami.i18n import t


@app.command(help=_tr("cli.run", _default="Single round-trip to the provider (Phase 0)."))
def run(
    prompt: str = typer.Argument(..., help=_tr("cli.run.prompt", _default="Prompt for the agent.")),
    provider: str = typer.Option(None, "--provider", "-p", help=_tr("cli.run.provider", _default="Provider name (default: from okami.yaml).")),
    model: str = typer.Option(None, "--model", "-m", help=_tr("cli.run.model", _default="Override the provider's model.")),
    system: str = typer.Option(None, "--system", "-s", help=_tr("cli.run.system", _default="Optional system prompt.")),
    no_stream: bool = typer.Option(False, "--no-stream", help=_tr("cli.run.no_stream", _default="Disable streaming.")),
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


@app.command("providers", help=_tr("cli.providers", _default="List configured providers and whether they are ready (★ = default)."))
def list_providers(
    json_out: bool = typer.Option(False, "--json", help=_tr("cli.providers.json", _default="Structured JSON output (scripts/CI).")),
) -> None:
    """Lista os providers configurados e se estão prontos (★ = default)."""
    cfg = _load()
    if json_out:
        import json as _json
        payload = {"default_provider": cfg.default_provider, "providers": {
            name: {"model": pc.model, "tier": pc.tier, "transport": pc.transport,
                   "api_base": pc.api_base or None, "ready": bool(pc.ready),
                   "experimental": bool(pc.experimental)}
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
        if pc.experimental:
            state = _ui.badge("warn", "experimental")          # opt-in, não "quebrado"
        elif pc.ready:
            state = _ui.badge("ready", "pronto")
        else:
            state = _ui.badge("missing", "falta auth")
        t.add_row(mark, name, pc.model, pc.tier, pc.transport, state)
    console.print(_ui.panel(t, title=f"Providers ({len(cfg.providers)})",
                            subtitle="★ default", accent=_ui.MAGENTA))
    console.print(_ui.footer("Próximos passos:", [
        ("okami provider add", "adiciona um modelo do catálogo (23 presets)"),
        ("okami provider default <id>", "troca o provider padrão"),
        ("okami login <id>", "autentica assinatura/OAuth"),
    ]))
    console.print()


@app.command(help=_tr("cli.doctor", _default="Diagnose config, keys and connectivity."))
def doctor(
    fix: bool = typer.Option(False, "--fix", help=_tr("cli.doctor.fix", _default="Fix what it can: orphan locks, .env perms, temp.")),
    json_out: bool = typer.Option(False, "--json", help=_tr("cli.doctor.json", _default="Structured JSON output (monitoring/CI).")),
    lint: bool = typer.Option(False, "--lint", help=_tr("cli.doctor.lint", _default="POSTURE lint (security/exposure), OpenClaw-style.")),
    ack: str = typer.Option("", "--ack", help=_tr("cli.doctor.ack", _default="Acknowledge a supply-chain advisory by id (stops warning).")),
) -> None:
    """Diagnostica config, chaves e conectividade. `--fix` repara; `--json` p/ máquina; `--lint` postura."""
    if ack:                                          # reconhece advisory de supply-chain (item 15)
        from okami.core import advisories
        ok = advisories.ack(ack)
        console.print(f"[green]✓[/green] advisory {ack} reconhecido." if ok
                      else f"[red]✗[/red] não consegui gravar o ack de {ack}.")
        raise typer.Exit(0)
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
        console.print("\n[dim]" + t("doctor.lint_summary", _default="{p} ok · {w} warnings · {f} failures",
                                    p=s["counts"]["pass"], w=s["counts"]["warn"], f=s["counts"]["fail"]) + "[/dim]")
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
        is_default = name == cfg.default_provider
        mark = Text("★", style=_ui.ORANGE) if is_default else Text(" ")
        # EXPERIMENTAL: opt-in, fora do failover → não pinga (não alarma com 401/parse de coisa em obras).
        if pc.experimental and not is_default:
            pt.add_row(mark, name, _ui.badge("warn", t("doctor.prov.experimental", _default="experimental")),
                       Text(t("doctor.prov.experimental_hint", _default="opt-in · unverified"), style=_ui.MUTE))
            continue
        # provider NÃO-pronto: é ERRO só se for o default; senão é OPCIONAL (não configurado), sem alarme.
        nrv = "missing" if is_default else "off"
        opt = "" if is_default else " · " + t("doctor.prov.optional", _default="optional")
        if pc.transport in ("codex_oauth", "minimax_oauth"):
            auth = (_ui.badge("ready", t("doctor.prov.logged_in", _default="logged in")) if pc.ready
                    else _ui.badge(nrv, f"login {name}{opt}"))
        elif pc.transport == "claude_cli":
            auth = (_ui.badge("ready", "CLI claude") if pc.ready
                    else _ui.badge(nrv, t("doctor.prov.install_cli", _default="install the CLI") + opt))
        elif pc.api_key_env:
            auth = (_ui.badge("ready", pc.api_key_env) if pc.resolved_key()
                    else _ui.badge(nrv, t("doctor.prov.set_env", _default="set {env}", env=pc.api_key_env) + opt))
        elif pc.api_key:
            auth = _ui.badge("ok", "literal/dummy")
        else:
            auth = _ui.badge("off", t("doctor.prov.none", _default="none"))
        # só pinga quem DEVERIA estar pronto (default ou autenticado) — não alarma com 401 de opcional.
        ep = Text("—", style=_ui.DIM)
        if pc.api_base and (is_default or pc.ready):
            ok, _msg, *_ = _ping_models(pc.api_base)    # tolera a 3-tupla (ok, msg, ids); só usa ok aqui
            host = pc.api_base.replace("https://", "").replace("http://", "")
            ep = Text()
            # default falhando = erro (vermelho); opcional falhando (auth ruim/401) = aviso (amber), não alarme.
            ep.append_text(_ui.dot("ok" if ok else ("fail" if is_default else "warn")))
            ep.append(f" {host}", style=_ui.MUTE)
        elif not pc.ready:
            ep = Text(t("doctor.prov.not_configured", _default="not configured"), style=_ui.MUTE)
        pt.add_row(mark, name, auth, ep)
    cards.append(_ui.panel(pt, title=f"Providers ({len(cfg.providers)})", accent=_ui.MAGENTA))

    # ◆ Memória ----------------------------------------------------------------
    mem = cfg.memory or {}
    emb = mem.get("embedder") or {}
    emb_v = Text(t("doctor.mem.off", _default="off"), style=_ui.MUTE)
    if emb.get("enabled", True) and emb.get("model"):
        from okami.memory import OpenAICompatEmbedder
        ok = OpenAICompatEmbedder(emb.get("api_base", "http://localhost:1234/v1"), emb["model"]).available()
        emb_v = _ui.badge("ok", "online") if ok else _ui.badge("warn", "offline → BM25")
    mem_rows = [
        ("backend", Text(mem.get("backend", "sqlite-fts5"), style=f"bold {_ui.FG}")),
        ("embedder", emb_v),
        ("honcho", Text((mem.get("honcho") or {}).get("base_url", "—"), style=_ui.SOFT)),
        (t("doctor.mem.files", _default="files"), Text("SOUL · VOICE · PERSONA · USER · MEMORY", style=_ui.SOFT)),
    ]
    cards.append(_ui.panel(_ui.fields(mem_rows, label_w=10), title=t("doctor.card.memory", _default="Memory"),
                           accent=_ui.CYAN))

    # ◆ Ambiente / toolchain ---------------------------------------------------
    # git/uv = essenciais; node/docker/claude/rg = recomendados (não quebram o core se faltarem).
    _RECOMMENDED = {"node", "docker", "claude", "rg"}
    tools_line = Text()
    for tool in ("git", "uv", "node", "docker", "claude", "rg"):
        path = shutil.which(tool)
        tools_line.append_text(_ui.dot("ok" if path else ("warn" if tool in _RECOMMENDED else "off")))
        tools_line.append(f" {tool}  ", style=_ui.SOFT if path else _ui.MUTE)
    if not shutil.which("rg"):                       # busca do agente usa grep como fallback — só recomendado
        tools_line.append("\n" + t("doctor.env.rg_missing",
                          _default="rg (ripgrep) missing — recommended for fast search; without it the agent uses grep."),
                          style=_ui.MUTE)
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
        env_v = Text(t("doctor.env.no_env", _default="none (okami config set …)"), style=_ui.MUTE)
    from okami.core.sandbox import SandboxPolicy
    sb = SandboxPolicy.from_config(getattr(cfg, "sandbox", {}) or {})
    sb_v = Text()
    sb_v.append(f"{sb.backend}·{sb.mode} ", style=_ui.FG)
    sb_v.append_text(_ui.badge("ok", t("doctor.env.isolated", _default="isolated")) if sb.backend == "docker"
                     else _ui.badge("warn", t("doctor.env.local_fences", _default="local fences")))
    from okami.integrations.mcp import servers_of
    srv = servers_of(getattr(cfg, "mcp", None))
    env_rows = [
        ("toolchain", tools_line),
        ("SQLite FTS5", _ui.badge("ok", t("doctor.env.hybrid", _default="hybrid")) if fts_ok
         else _ui.badge("warn", t("doctor.env.like_no_fts", _default="LIKE (no FTS5)"))),
        ("codex auth", _ui.badge("ok", t("doctor.prov.logged_in", _default="logged in")) if codex_auth
         else _ui.badge("missing", "okami login codex")),
        (".env global", env_v),
        ("MCP", Text(t("doctor.env.servers", _default="{n} server(s)", n=len(srv)) if srv
                     else t("doctor.prov.none", _default="none"), style=_ui.SOFT if srv else _ui.MUTE)),
        ("sandbox", sb_v),
    ]
    cards.append(_ui.panel(_ui.fields(env_rows, label_w=12),
                           title=t("doctor.card.environment", _default="Environment"), accent=_ui.ORANGE))

    # ◆ Disco (medidores) ------------------------------------------------------
    cards.append(_ui.panel(_disk_renderable(cfg, as_meters=True),
                           title=t("doctor.card.disk", _default="Disk"), accent=_ui.MAGENTA))

    console.print(_ui.grid(cards, width=console.width))

    from okami.core import advisories            # supply-chain: pacote comprometido instalado? (item 15)
    hits = advisories.detect_compromised(include_acked=False)
    if hits:
        console.print()
        for h in hits:
            console.print(f"[bold red]🛑 SUPPLY-CHAIN[/bold red] {h['package']}=={h['installed']} "
                          f"[red]({h['severity']})[/red] — {h['why']}")
            console.print(f"   [dim]reconheça com: okami doctor --ack {h['id']}[/dim]")
    from okami.home import agent_locations       # config de agente em dois lugares → "não está salvando"
    _al = agent_locations()
    if _al["diverges"]:
        console.print()
        console.print("[bold yellow]⚠ CONFIG DE AGENTE EM DOIS LUGARES[/bold yellow] — fonte de "
                      "\"o sistema não salva\":")
        console.print(f"   comandos de config (deste diretório) gravam em [bold]{_al['effective']}[/bold] "
                      f"({', '.join(_al['effective_agents']) or '—'})")
        console.print(f"   o gateway rodado da HOME/serviço lê [bold]{_al['global']}[/bold] "
                      f"({', '.join(_al['global_agents']) or '—'})")
        console.print("   [dim]→ configure de FORA do projeto (do seu ~) p/ acertar o que o gateway lê, "
                      "ou suba o gateway de dentro do projeto.[/dim]")
    console.print(_ui.footer(t("doctor.next_steps", _default="Next steps:"), [
        ("okami doctor --lint", t("doctor.step.lint", _default="security posture lint")),
        ("okami clean --deep --dry-run", t("doctor.step.clean", _default="disk cleanup preview (versioned quota)")),
        ("okami login <provider>", t("doctor.step.login", _default="authenticate a subscription provider")),
    ]))
    console.print()

    if fix:
        from okami.config import global_env_path
        from okami.core.maintenance import clean_stale_locks, fix_env_perms, prune_temp, repair_dbs_under
        console.print("\n[bold]--fix[/bold]")
        locks = clean_stale_locks(".")
        env_p = global_env_path()
        env_fixed = fix_env_perms(env_p)
        rm_t, freed = prune_temp(".")
        console.print("  " + t("doctor.fix.locks", _default="orphan locks removed: [bold]{n}[/bold]", n=len(locks)))
        _perms = ("[yellow]" + t("doctor.fix.perms_fixed", _default="fixed → 0600") + "[/yellow]") if env_fixed \
            else "[green]ok[/green]"
        console.print(f"  {env_p} perms: {_perms}")
        console.print("  " + t("doctor.fix.temp", _default="temp files removed: [bold]{n}[/bold] [dim]({kb:.1f} KB)[/dim]",
                               n=len(rm_t), kb=freed / 1024))
        # #10: recupera SQLite malformado (state.db/memória) no HOME — backup + dump/reload.
        from okami.home import okami_home
        dbs = repair_dbs_under(okami_home())
        broken = [r for r in dbs if r["action"] != "healthy"]
        if broken:
            for r in broken:
                console.print(f"  [yellow]DB {r['path']}: {r['action']}[/yellow]"
                              + (f" [dim](backup: {r.get('backup')})[/dim]" if r.get("backup") else ""))
        else:
            console.print("  " + t("doctor.fix.dbs", _default="SQLite DBs: [green]all healthy[/green] ({n})", n=len(dbs)))


@app.command(help=_tr("cli.plugins", _default="List discovered plugins (folder + pip entry-points)."))
def plugins() -> None:
    """#12: lista plugins descobertos (pasta .okami/plugins/ + entry-point pip okami.plugins)."""
    from okami.plugins import discover_plugins, plugin_roots
    found = discover_plugins(plugin_roots())
    if not found:
        console.print("[dim]nenhum plugin instalado (.okami/plugins/<nome>/plugin.yaml ou entry-point pip).[/dim]")
        return
    for p in found:
        console.print(f"  [bold]{p.name}[/bold] [dim]({p.source})[/dim] hooks: {', '.join(p.hooks) or '—'}")


@app.command(help=_tr("cli.gui", _default="Open the web dashboard (status/sessions/config/logs) in your browser."))
def gui(
    port: int = typer.Option(9119, "--port", help=_tr("cli.gui.port", _default="Port for the local dashboard.")),
    no_open: bool = typer.Option(False, "--no-open", help=_tr("cli.gui.no_open", _default="Don't open the browser, just serve.")),
    app_window: bool = typer.Option(False, "--app", help=_tr("cli.gui.app", _default="Open in an app-mode window (chrome --app) instead of a tab.")),
    workspace: str = typer.Option(".", "-w", "--workspace"),
) -> None:
    """#12/#14: dashboard web (stdlib, zero-dep) — status/sessões/config(read-only)/logs. Localhost."""
    import threading
    from okami.gateway.web import default_providers, serve_dashboard

    url = f"http://127.0.0.1:{port}/"
    console.print(f"[green]dashboard em[/green] {url} [dim](Ctrl-C p/ parar)[/dim]")
    if not no_open:
        threading.Timer(0.6, lambda: _open_dashboard(url, app_window)).start()
    try:
        serve_dashboard(port, providers=default_providers(workspace))
    except KeyboardInterrupt:
        console.print("\n[dim]dashboard parado.[/dim]")
    except OSError as e:
        console.print(f"[red]não subiu ({e})[/red] — porta ocupada? tente --port outro.")
        raise typer.Exit(1) from e


def _open_dashboard(url: str, app_window: bool) -> None:
    """Abre o dashboard: janela app-mode (chrome/edge --app) se pedido e disponível, senão browser normal."""
    import shutil
    import subprocess
    import webbrowser
    if app_window:
        for binexe in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"):
            path = shutil.which(binexe)
            if path:
                try:
                    subprocess.Popen([path, f"--app={url}"])  # noqa: S603
                    return
                except OSError:
                    break
        if shutil.which("open"):                          # macOS: tenta o Chrome app-mode
            try:
                subprocess.Popen(["open", "-na", "Google Chrome", "--args", f"--app={url}"])  # noqa: S603,S607
                return
            except OSError:
                pass
    webbrowser.open(url)


@app.command(help=_tr("cli.desktop", _default="Open the dashboard as a desktop app window (alias for `gui --app`)."))
def desktop(
    port: int = typer.Option(9119, "--port", help=_tr("cli.desktop.port", _default="Port for the local dashboard.")),
    workspace: str = typer.Option(".", "-w", "--workspace"),
) -> None:
    """#14: experiência 'desktop' sem Electron — abre o dashboard numa janela app-mode do browser."""
    gui(port=port, no_open=False, app_window=True, workspace=workspace)


@app.command(help=_tr("cli.blueprint", _default="Parameterized automations: okami blueprint list | show <key> | use <key> [slot=val ...]."))
def blueprint(
    action: str = typer.Argument("list", help=_tr("cli.blueprint.action", _default="list | show | use")),
    key: str = typer.Argument("", help=_tr("cli.blueprint.key", _default="blueprint key (for show/use)")),
    slots: list[str] = typer.Argument(None, help=_tr("cli.blueprint.slots", _default="slot=value pairs (for use)")),
    workspace: str = typer.Option(".", "-w", "--workspace"),
) -> None:
    """#12: automação parametrizada. `okami blueprint use daily-briefing time=09:00 days=weekdays`."""
    from okami.automation.blueprints import (
        CATALOG, BlueprintFillError, blueprint_slash_command, fill_blueprint, get_blueprint,
    )
    if action == "list":
        for k, bp in sorted(CATALOG.items()):
            console.print(f"  [bold]{k}[/bold] — {bp.description}")
        return
    if not key:
        console.print("[red]informe a key:[/red] okami blueprint show <key>")
        raise typer.Exit(2)
    try:
        bp = get_blueprint(key)
    except KeyError:
        console.print(f"[red]blueprint '{key}' não existe[/red] [dim](okami blueprint list)[/dim]")
        raise typer.Exit(1) from None
    if action == "show":
        console.print(f"[bold]{bp.title}[/bold] — {bp.description}\n{blueprint_slash_command(bp)}")
        for s in bp.slots:
            console.print(f"  · {s.name} ({s.type}) default={s.default} {('— ' + s.help) if s.help else ''}")
        return
    if action == "use":
        vals = dict(p.split("=", 1) for p in (slots or []) if "=" in p)
        try:
            kw = fill_blueprint(bp, vals)
        except BlueprintFillError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(2) from e
        from okami.automation.scheduler import Scheduler
        job = Scheduler(workspace).add(kw["schedule"], kw["prompt"], target=kw.get("target"))
        console.print(f"[green]✓ automação criada[/green] {job['id']} · {kw['schedule']} [dim](blueprint {key})[/dim]")
        return
    console.print(f"[red]ação '{action}' não reconhecida[/red] — use: list | show | use")
    raise typer.Exit(2)


@app.command(help=_tr("cli.swarm", _default="Plan (or run) a worker→verifier→synthesizer swarm for a goal."))
def swarm(
    goal: str = typer.Argument(..., help=_tr("cli.swarm.goal", _default="The goal to farm out to specialists.")),
    worker: list[str] = typer.Option(None, "--worker", help=_tr("cli.swarm.worker", _default="title:body of a worker (repeatable).")),
    run: bool = typer.Option(False, "--run", help=_tr("cli.swarm.run", _default="Actually execute the swarm (spawn workers→verifier→synthesizer).")),
    workspace: str = typer.Option(".", "-w", "--workspace"),
) -> None:
    """#12/#14: monta — e com --run EXECUTA — o enxame (workers → verificador → sintetizador)."""
    from okami.automation.swarm import build_swarm_plan, run_swarm
    workers = []
    for w in (worker or []):
        title, _, body = w.partition(":")
        workers.append({"title": title.strip(), "body": body.strip() or title.strip()})
    if not workers:
        workers = [{"title": "pesquisa", "body": "investigue a fundo"},
                   {"title": "revisão", "body": "valide e critique"}]
    if not run:
        plan = build_swarm_plan(goal, workers)
        console.print(f"[bold]Swarm:[/bold] {plan['goal']} [dim](blackboard {plan['blackboard']})[/dim]")
        for i, w in enumerate(plan["workers"], 1):
            console.print(f"  worker {i} [{w['title']}]: {w['prompt'].splitlines()[2][:80]}")
        console.print("  verificador → sintetizador [dim](use --run p/ executar)[/dim]")
        return
    from okami.cli._shared import _load
    from okami.runner import run_task
    cfg = _load()

    def _run_fn(prompt: str) -> str:
        t = run_task(cfg, workspace, prompt, surface="cli")
        return t.result or t.reason or ""

    console.print(f"[bold]Executando swarm:[/bold] {goal} …")
    res = run_swarm(goal, workers, run_fn=_run_fn)
    console.print(f"\n[bold green]Síntese:[/bold green]\n{res['synthesis']}")


@app.command(help=_tr("cli.deps", _default="Manage optional backends (lazy deps): okami deps list | install <feature>."))
def deps(
    action: str = typer.Argument("list", help=_tr("cli.deps.action", _default="list | install")),
    feature: str = typer.Argument("", help=_tr("cli.deps.feature", _default="feature name (e.g. provider.gemini), for install")),
) -> None:
    """#12: instala backend opcional sob demanda (allowlist, venv-scoped). `okami deps install provider.gemini`."""
    from okami.core.lazy_deps import LAZY_DEPS, FeatureUnavailable, ensure, feature_missing
    if action == "list":
        for k in sorted(LAZY_DEPS):
            miss = feature_missing(k)
            mark = "[yellow]falta[/yellow]" if miss else "[green]ok[/green]"
            console.print(f"  {mark}  [bold]{k}[/bold] [dim]({', '.join(LAZY_DEPS[k])})[/dim]")
        return
    if action == "install":
        if not feature:
            console.print("[red]informe a feature:[/red] okami deps install provider.gemini")
            raise typer.Exit(2)
        try:
            ensure(feature, prompt=False)
            console.print(f"[green]✓ {feature} pronto[/green]")
        except FeatureUnavailable as e:
            console.print(f"[red]falhou:[/red] {e}")
            raise typer.Exit(1) from e
        return
    console.print(f"[red]ação '{action}' não reconhecida[/red] — use: list | install")
    raise typer.Exit(2)


@app.command(help=_tr("cli.completion", _default="Print a shell-completion snippet (bash/zsh/fish) to source in your shell rc."))
def completion(
    shell: str = typer.Argument("bash", help=_tr("cli.completion.shell", _default="Shell: bash, zsh or fish.")),
) -> None:
    """#11: tab-completion zero-setup. `okami completion zsh >> ~/.zshrc` (ou source no rc)."""
    from okami.cli.completion import completion_script
    snippet = completion_script(shell)
    if snippet is None:
        console.print(f"[red]shell não suportado:[/red] {shell} [dim](use bash, zsh ou fish)[/dim]")
        raise typer.Exit(1)
    console.print(snippet, end="")


@app.command(help=_tr("cli.harden", _default="Apply the HARDENED-STRICT profile (recommended posture for public/GA)."))
def harden(
    off: bool = typer.Option(False, "--off", help=_tr("cli.harden.off", _default="Turn off strict isolation (back to dev-friendly).")),
) -> None:
    """Aplica o perfil HARDENED-STRICT — a postura recomendada p/ produção pública/GA (#2): superfície
    exposta SEM Docker → run_shell/process DESABILITADOS, não degradam pro host. Grava
    `sandbox.profile: hardened-strict` no okami.local.yaml (o `okami policy check --strict` passa).

    Use ANTES de expor o gateway publicamente ('qualquer um manda mensagem'). CLI/dev local não muda."""

    from okami.core.safe_io import read_yaml_resilient, secure_write_yaml
    p = Path("okami.local.yaml")
    data = read_yaml_resilient(p, default={}) or {}
    sb = dict(data.get("sandbox") or {})
    if off:
        if str(sb.get("profile", "")) == "hardened-strict":
            sb.pop("profile", None)
        sb.pop("require_isolation", None)            # limpa também o flag legado de versões antigas do harden
    else:
        sb["profile"] = "hardened-strict"            # postura NOMEADA (vence em runtime e no check estrito)
        sb.pop("require_isolation", None)            # o profile já implica isolamento — evita config redundante
    if sb:
        data["sandbox"] = sb
    else:
        data.pop("sandbox", None)                    # não deixa um `sandbox: {}` vazio depois do --off
    secure_write_yaml(p, data)
    if off:
        console.print("[yellow]⚠ perfil hardened-strict DESLIGADO[/yellow] — superfície exposta volta a degradar "
                      "p/ local sem Docker (dev-friendly). NÃO recomendado p/ uso público.")
        return
    console.print("[green]✓ perfil hardened-strict LIGADO[/green] [dim](sandbox.profile: hardened-strict em "
                  "okami.local.yaml)[/dim]")
    from okami.core.sandbox import SandboxPolicy
    has_docker = SandboxPolicy.from_config({"backend": "auto"}).effective_backend() == "docker"
    if not has_docker:
        console.print("[yellow]   Docker NÃO detectado[/yellow] — em superfície exposta o run_shell/process "
                      "ficará DESABILITADO (fail-closed) até ter Docker. É o comportamento seguro p/ GA.")
    console.print("[dim]   Verifique: okami policy check --strict  ·  reverter: okami harden --off[/dim]")


@app.command(help=_tr("cli.login", _default="Authenticate a subscription provider (device flow / official CLI)."))
def login(
    provider: str = typer.Argument(..., help=_tr("cli.login.provider", _default="Provider to authenticate (e.g. codex, minimax).")),
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
        if oauth.codex_logged_in():     # re-login/troca de conta: diz quem está logado e que isto SUBSTITUI
            who = oauth.codex_email() or oauth.codex_account_id() or "conta atual"
            console.print(f"[dim]já logado como[/dim] [bold]{who}[/bold] [dim]— este login SUBSTITUI "
                          f"(troca de conta / renova quando o plano acaba). Abra o link com a conta desejada.[/dim]")
        try:
            oauth.codex_device_login(lambda m: console.print(m))
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Falha no login:[/red] {e}")
            console.print("[dim]dica: confira a hora do sistema e a conexão; se persistir, rode "
                          "`okami logout codex` e tente de novo.[/dim]")
            raise typer.Exit(1)
        console.print(f"[green]✓ login '{provider}' concluído[/green] [dim](okami status mostra a conta)[/dim]")
        return

    if pc.login_cmd:  # delega ao CLI oficial (fallback opcional)
        console.print(f"[dim]delegando para:[/dim] {' '.join(pc.login_cmd)}")
        try:
            rc = oauth.cli_delegate_login(pc.login_cmd)
        except FileNotFoundError:
            console.print(f"[red]CLI '{pc.login_cmd[0]}' não encontrado.[/red] Instale-o e tente de novo.")
            raise typer.Exit(1)
        raise typer.Exit(rc)

    if pc.oauth:  # device flow nativo genérico
        try:
            oauth.device_login(provider, pc.oauth, lambda m: console.print(m))
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Falha no login:[/red] {e}")
            raise typer.Exit(1)
        console.print(f"[green]✓ login '{provider}' concluído[/green]")
        return

    if pc.api_key_env:  # provider por API KEY (minimax/mimo/openai/…): "autenticar" = gravar a chave no .env
        if pc.resolved_key():
            console.print(f"[green]✓ '{provider}' já autenticado[/green] [dim]({pc.api_key_env} no .env)[/dim] — "
                          f"cole de novo só p/ trocar.")
        from okami import menu
        from okami.cli._shared import _set_env_var
        key = menu.text(f"Cole a API key de '{provider}' ({pc.api_key_env}) — fica oculta, vai pro .env",
                        password=True).strip()
        if not key:
            console.print(f"[yellow]cancelado.[/yellow] Defina {pc.api_key_env} quando tiver a chave "
                          f"(ou: okami config set {pc.api_key_env} <key>).")
            raise typer.Exit(1)
        _set_env_var(pc.api_key_env, key)               # .env GLOBAL, atômico + 0600
        console.print(f"[green]✓ '{provider}' autenticado[/green] [dim]({pc.api_key_env} salvo no .env)[/dim] — "
                      "confira com: okami doctor")
        return

    console.print(f"[yellow]'{provider}' não tem fluxo de login.[/yellow] Use .env/api_key.")


@app.command(help=_tr("cli.logout", _default="Log out of a provider: delete the stored credential (to switch accounts or when the plan ends)."))
def logout(
    provider: str = typer.Argument(..., help=_tr("cli.logout.provider", _default="Provider to log out of (e.g. codex, minimax).")),
) -> None:
    """Sai de um provider: apaga a credencial guardada (p/ trocar de conta ou quando o plano acaba)."""
    from okami.llm import oauth

    cfg = _load()
    try:
        pc = cfg.provider(provider)
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if pc.api_key_env:   # api_key: a credencial é a env var no .env — não apagamos o .env, só orientamos
        console.print(f"[yellow]'{provider}' usa API key ({pc.api_key_env}).[/yellow] Remova {pc.api_key_env} do "
                      f".env (ou rode `okami login {provider}` p/ colar outra).")
        return

    res = oauth.logout(provider)
    if res["removed"]:
        console.print(f"[green]✓ saiu de '{provider}'[/green] [dim](credencial OAuth removida)[/dim]")
    else:
        console.print(f"[dim]'{provider}' já não tinha credencial guardada.[/dim]")
    if res["cli_auth"]:   # o codex CLI tem auth.json próprio, que serve de FALLBACK — avise
        console.print("[yellow]aviso:[/yellow] o codex CLI ainda tem login próprio (~/.codex), usado como "
                      "fallback. Pra trocar de conta de vez, rode `codex logout` (ou relogue) também.")
    console.print(f"[dim]re-autenticar: okami login {provider}[/dim]")


@app.command(help=_tr("cli.gate", _default="Run the design verification gate (§4.3) over a directory."))
def gate(
    path: str = typer.Argument(".", help=_tr("cli.gate.path", _default="Directory to check.")),
    contract: str = typer.Option("ui", "--contract", "-c", help=_tr("cli.gate.contract", _default="Contract name in okami.yaml.")),
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


