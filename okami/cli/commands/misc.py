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
    from rich.text import Text

    from okami.cli import _ui
    from okami.core.auth_profiles import build_auth_profiles
    profs = build_auth_profiles(_load())
    console.print()
    console.print(_ui.header("auth", "perfis de credencial · sem expor o valor"))
    console.print()
    t = _ui.data_table(
        ("", {"width": 2, "no_wrap": True}),
        ("provider", {"style": f"bold {_ui.FG}", "no_wrap": True}),
        ("tipo", {"style": _ui.MUTE, "no_wrap": True}),
        ("sub", {"justify": "center", "no_wrap": True}),
        ("status", {"no_wrap": True}),
        ("credencial (onde)", {"style": _ui.SOFT, "overflow": "ellipsis", "no_wrap": True}),
    )
    for p in profs:
        mark = Text("★", style=_ui.ORANGE) if p["default"] else Text(" ")
        sub = Text("✓", style=f"bold {_ui.GREEN}") if p["subscription"] else Text("—", style=_ui.MUTE)
        t.add_row(mark, p["name"], p["kind"], sub, _ui.badge(p["status"]), p["location"])
    console.print(t)
    console.print(_ui.hint("★ default · sub ✓ = assinatura OAuth/CLI (nunca pay-as-you-go) · okami login <provider>"))
    console.print()


@auth_app.command("status")
def auth_status(json_out: bool = typer.Option(False, "--json", help="Saída JSON (monitoramento/CI).")) -> None:
    """Status dos perfis de auth (machine-readable com --json)."""
    from okami.core.auth_profiles import build_auth_profiles
    profs = build_auth_profiles(_load())
    if json_out:
        import json as _json
        console.print_json(_json.dumps({"profiles": profs}, ensure_ascii=False))
        raise typer.Exit(0 if all(p["status"] != "missing" or not p["default"] for p in profs) else 1)
    from rich.text import Text

    from okami.cli import _ui
    for p in profs:
        line = Text("  ")
        line.append_text(_ui.badge(p["status"]))
        line.append(f"  {p['name']}", style=f"bold {_ui.FG}")
        line.append(f"   {p['kind']} · {p['location']}", style=_ui.MUTE)
        console.print(line)


policy_app = typer.Typer(help="Conformance de POLÍTICA autorada (#P1.3): `okami policy check/init/show`.")
app.add_typer(policy_app, name="policy")


def _collect_channels():
    """Canais p/ a policy: bloco global `channels` + por-agente (agent.yaml), best-effort."""
    from okami.config import load_raw
    from okami.core.policy import collect_channels
    raw, _ = load_raw()
    agents = {}
    try:
        from okami.agents import load_agents
        agents = load_agents()
    except Exception:  # noqa: BLE001
        agents = {}
    return raw, collect_channels(raw, agents)


@policy_app.command("check")
def policy_check(
    json_out: bool = typer.Option(False, "--json", help="Artefato de conformance JSON (CI/pre-deploy)."),
    policy_file: str = typer.Option(None, "--policy", help="Caminho do okami.policy.yaml (default: auto-descobre)."),
    strict: bool = typer.Option(False, "--strict", help="Postura de PRODUÇÃO/GA (ambiente hostil/público)."),
) -> None:
    """Avalia config+workspace contra a policy AUTORADA. `--strict` = posture de produção. Exit≠0 se falha."""
    from pathlib import Path as _P

    from okami.core.lint import summarize
    from okami.core.policy import conformance_artifact, evaluate, load_policy, strict_policy
    policy, source = load_policy(_P(policy_file) if policy_file else None)
    if strict:
        policy, source = strict_policy(policy), f"{source} + produção (--strict)"
    raw, channels = _collect_channels()
    findings = evaluate(_load(), policy, raw=raw, channels=channels)
    s = summarize(findings)
    if json_out:
        import json as _json
        console.print_json(_json.dumps(conformance_artifact(findings, policy_source=source), ensure_ascii=False))
        raise typer.Exit(0 if s["ok"] else 1)
    from rich.text import Text

    from okami.cli import _ui
    console.print()
    console.print(_ui.header("policy check", source + (" · produção" if strict else "")))
    console.print()
    shown = [x for x in findings if x.level != "pass"]
    if not shown:
        console.print(_ui.badge("pass", "nenhum desvio — tudo conforme"))
    for x in shown:
        line = Text("  ")
        line.append_text(_ui.dot(x.level))
        line.append(f"  {x.check}", style=f"bold {_ui.FG}")
        line.append(f"   {x.message}", style=_ui.SOFT)
        console.print(line)
        if x.fix:
            console.print(Text("       ").append_text(_ui.hint(x.fix)))
    console.print()
    c = s["counts"]
    verdict = Text("  ")
    verdict.append_text(_ui.badge("ok", "conforme") if s["ok"] else _ui.badge("fail", f"{c['fail']} falha(s)"))
    verdict.append(f"    {c['pass']} ok · {c['warn']} avisos · {c['fail']} falhas", style=_ui.MUTE)
    console.print(verdict)
    console.print()
    raise typer.Exit(0 if s["ok"] else 1)


@policy_app.command("init")
def policy_init(
    force: bool = typer.Option(False, "--force", help="Sobrescreve um okami.policy.yaml existente."),
) -> None:
    """Cria um okami.policy.yaml inicial (baseline comentada) p/ você autorar a conformance."""
    from okami.core.policy import scaffold
    p = Path("okami.policy.yaml")
    if p.exists() and not force:
        console.print("[yellow]okami.policy.yaml já existe[/yellow] — use --force p/ sobrescrever.")
        raise typer.Exit(1)
    p.write_text(scaffold(), encoding="utf-8")
    console.print("[green]✓ okami.policy.yaml criado[/green] [dim](edite e rode: okami policy check)[/dim]")


@policy_app.command("show")
def policy_show(
    strict: bool = typer.Option(False, "--strict", help="Mostra a postura de PRODUÇÃO/GA (overlay aplicado)."),
) -> None:
    """Mostra a policy EFETIVA (baseline + okami.policy.yaml autorado; --strict aplica a postura de produção)."""
    import yaml as _yaml

    from okami.core.policy import load_policy, strict_policy
    policy, source = load_policy()
    if strict:
        policy, source = strict_policy(policy), f"{source} + produção"
    if not console.is_terminal:                       # pipe → YAML cru (com a fonte como comentário)
        console.print(f"# policy: {source}")
        console.print(_yaml.safe_dump(policy, allow_unicode=True, sort_keys=False))
        return
    from rich.syntax import Syntax

    from okami.cli import _ui
    console.print()
    console.print(_ui.header("policy", "política de conformance efetiva"))
    console.print()
    body = Syntax(_yaml.safe_dump(policy, allow_unicode=True, sort_keys=False), "yaml",
                  theme="ansi_dark", background_color="default")
    console.print(_ui.card(body, title="policy", subtitle=source))


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
def replay(
    trace: str = typer.Argument(None, help="trace_id do turno (sem arg = lista os turnos recentes)."),
    agent: str = typer.Option(None, "-a", "--agent"),
    workspace: str = typer.Option(".", "-w", "--workspace"),
    json_out: bool = typer.Option(False, "--json", help="Saída JSON (CI/ferramenta)."),
) -> None:
    """Replay da TRAJETÓRIA de um turno (#12): `okami replay` lista turnos; `okami replay <trace>` detalha."""
    import datetime as _dt

    from okami.observability.trajectory import build_trajectory, list_traces, render_line
    ws = _persona_ws(agent, workspace)
    if not trace:                                     # sem trace → lista os turnos p/ escolher
        traces = list_traces(ws)
        if json_out:
            import json as _json
            console.print_json(_json.dumps({"traces": traces}, ensure_ascii=False))
            return
        from okami.cli import _ui
        console.print()
        console.print(_ui.header("replay", "trajetórias dos turnos recentes"))
        console.print()
        if not traces:
            console.print(_ui.hint(f"sem turnos em {ws}/.okami/events.jsonl"))
            return
        t = _ui.data_table(
            ("trace", {"style": f"bold {_ui.CYAN}", "no_wrap": True}),
            ("quando", {"style": _ui.MUTE, "no_wrap": True}),
            ("passos", {"justify": "right", "no_wrap": True}),
            ("llm", {"justify": "right", "no_wrap": True}),
            ("tokens", {"style": _ui.MUTE, "no_wrap": True}),
            ("desfecho", {"no_wrap": True}),
            ("objetivo", {"style": _ui.SOFT, "overflow": "ellipsis", "no_wrap": True}),
        )
        for s in traces:
            when = (_dt.datetime.fromtimestamp(s["ended_at"]).strftime("%m-%d %H:%M")
                    if s.get("ended_at") else "—")
            t.add_row(s["trace"], when, str(s["steps"]), str(s["llm_calls"]),
                      f"↑{s['tokens_in']} ↓{s['tokens_out']}", s["outcome"], str(s["goal"]))
        console.print(t)
        console.print(_ui.hint("okami replay <trace> — trajetória completa do turno"))
        console.print()
        return
    traj = build_trajectory(ws, trace)
    if json_out:
        import json as _json
        console.print_json(_json.dumps(traj, ensure_ascii=False))
        return
    if not traj["events"]:
        console.print(f"[yellow]trace '{trace}' não encontrado[/yellow] em {ws}/.okami/events.jsonl")
        raise typer.Exit(1)
    from okami.cli import _ui
    s = traj["summary"]
    console.print()
    console.print(_ui.header(f"replay {trace}",
                             f"{s['outcome']} · {s['steps']} passos · {s['llm_calls']} LLM · "
                             f"↑{s['tokens_in']} ↓{s['tokens_out']}"))
    console.print()
    for e in traj["events"]:
        console.print(render_line(e))
    console.print()


@app.command()
def clean(
    workspace: str = typer.Option(".", "-w", "--workspace"),
    lock_stale: float = typer.Option(300.0, "--lock-stale", help="Idade (s) p/ considerar um .lock órfão."),
    deep: bool = typer.Option(False, "--deep", help="Aplica a RETENÇÃO declarada (sessions/checkpoints/tool_outputs)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Só MOSTRA o que seria removido (não apaga)."),
    json_out: bool = typer.Option(False, "--json", help="Relatório por área em JSON (cron/monitoramento)."),
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


@app.command()
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


@app.command()
def status(
    json_out: bool = typer.Option(False, "--json", help="Saída em JSON estruturado (monitoramento/CI)."),
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
        from okami.core.lint import lint_posture, summarize
        from okami.core.maintenance import disk_report
        from okami.integrations.mcp import servers_of
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
            "mcp_servers": sorted(servers_of(cfg.mcp)),   # #P1: mcp.servers.<n>, não a chave 'servers'
            "lint": summarize(lint_posture(cfg)),
            "disk": disk_report(".", retention=cfg.retention),   # uso por área + quota (gateway long-running)
        }
        import json as _json
        console.print_json(_json.dumps(payload, ensure_ascii=False))
        raise typer.Exit(0)
    import os as _os

    from rich.text import Text

    from okami import __version__
    from okami.cli import _ui
    from okami.cli._shared import _disk_renderable
    default_agent = (cfg.agents or {}).get("default", "—")
    pc = cfg.provider()
    appr = (cfg.approvals or {}).get("mode", "manual")
    persona_on = (cfg.persona or {}).get("observe", True)
    learn = cfg.learning or {}
    voice_on = bool((cfg.voice or {}).get("stt") or (cfg.voice or {}).get("tts"))
    think = pc.reasoning_effort or "—"
    from okami.core.lint import lint_posture, summarize
    cs = summarize(lint_posture(cfg))
    cc = cs["counts"]

    # masthead: estado-resumo à direita (conforme / N falhas) -------------------
    right = "● tudo conforme" if cs["ok"] else f"✗ {cc['fail']} falha(s) de conformance"
    console.print()
    console.print(_ui.masthead(__version__, right=right))
    console.print()

    cards = []

    # ◆ Sessão -----------------------------------------------------------------
    model_v = Text(pc.model, style=f"bold {_ui.CYAN}", overflow="fold")
    model_v.append(f"\n{cfg.default_provider} · {pc.tier}", style=_ui.MUTE)
    toggles = Text()
    for lbl, on in (("persona", persona_on), ("voz", voice_on), ("auto-skill", learn.get("auto_skill"))):
        toggles.append_text(_ui.dot("on" if on else "off"))
        toggles.append(f" {lbl}  ", style=_ui.SOFT if on else _ui.MUTE)
    cards.append(_ui.panel(_ui.fields([
        ("agente", Text(default_agent, style=f"bold {_ui.FG}")),
        ("modelo", model_v),
        ("raciocínio", think),
        ("memória", cfg.memory.get("backend", "sqlite-fts5")),
        ("aprovação", _ui.badge("ok" if appr in ("manual", "smart") else "warn", appr)),
        ("recursos", toggles),
    ], label_w=11), title="Sessão", accent=_ui.ORANGE))

    # ◆ Providers --------------------------------------------------------------
    t = _ui.data_table(
        ("", {"width": 1, "no_wrap": True}),
        ("provider", {"style": f"bold {_ui.FG}", "no_wrap": True}),
        ("modelo", {"style": _ui.SOFT, "overflow": "ellipsis", "max_width": 18}),
        ("estado", {"no_wrap": True}),
    )
    for name, p in cfg.providers.items():
        mark = Text("★", style=_ui.ORANGE) if name == cfg.default_provider else Text(" ")
        state = _ui.badge("ready", "pronto") if p.ready else _ui.badge("missing", "falta auth")
        t.add_row(mark, name, p.model, state)
    cards.append(_ui.panel(t, title=f"Providers ({len(cfg.providers)})", accent=_ui.MAGENTA))

    # ◆ Canais & Gateway -------------------------------------------------------
    raw, channels = _collect_channels()
    ch_rows = []
    for (owner, ctype), conf in (channels or {}).items():
        if conf.get("allow_all"):
            st = _ui.badge("warn", "ingress ABERTO")
        elif conf.get("allow_chats"):
            st = _ui.badge("ok", f"allowlist ({len(conf['allow_chats'])})")
        else:
            st = _ui.badge("off", "deny-by-default")
        ch_rows.append((ctype + ("" if owner == "(global)" else f"·{owner}"), st))
    if not ch_rows:
        ch_rows.append(("canais", Text("nenhum — DM local (okami chat)", style=_ui.MUTE)))
    host = (cfg.gateway or {}).get("host", "127.0.0.1")
    api_tok = bool(_os.getenv("OKAMI_API_TOKEN"))
    api_v = Text()
    api_v.append_text(_ui.dot("ok" if (host in ("127.0.0.1", "localhost") or api_tok) else "warn"))
    api_v.append(f" {host} · token {'set' if api_tok else 'OFF'}", style=_ui.SOFT)
    ch_rows.append(("API", api_v))
    cards.append(_ui.panel(_ui.fields(ch_rows, label_w=14), title="Canais & Gateway", accent=_ui.CYAN))

    # ◆ MCP + Conformance ------------------------------------------------------
    from okami.integrations.mcp import _trust_of, servers_of
    srv = servers_of(cfg.mcp)
    cf = Text()
    cf.append_text(_ui.badge("ok", "conforme") if cs["ok"] else _ui.badge("fail", f"{cc['fail']} falha(s)"))
    cf.append(f"  {cc['pass']} ok · {cc['warn']} avisos", style=_ui.MUTE)
    mcp_rows = [("conformance", cf)]
    if srv:
        for n, c in srv.items():
            mcp_rows.append((f"mcp·{n}", Text(f"trust={_trust_of(c or {})}", style=_ui.SOFT)))
    else:
        mcp_rows.append(("mcp", Text("nenhum servidor", style=_ui.MUTE)))
    cards.append(_ui.panel(_ui.fields(mcp_rows, label_w=14), title="MCP & Conformance", accent=_ui.ORANGE))

    # ◆ Disco (medidores) ------------------------------------------------------
    cards.append(_ui.panel(_disk_renderable(cfg, as_meters=True), title="Disco", accent=_ui.MAGENTA))

    # ◆ Uso (tokens/custo) -----------------------------------------------------
    try:
        from okami.gateway.sessions import TranscriptStore
        from okami.llm.usage import estimate_cost, format_tokens, summarize_store
        ws = Path("agents") / default_agent if default_agent and default_agent != "—" else Path(".")
        u = summarize_store(TranscriptStore(ws).load_store())
        if u.total_tokens:
            cr = estimate_cost(u, transport=pc.transport, provider=cfg.default_provider, model=pc.model)
            usage = Text()
            usage.append(f"{format_tokens(u.input_tokens)} in", style=_ui.FG)
            usage.append(f" · {format_tokens(u.output_tokens)} out", style=_ui.SOFT)
            if u.cache_read_tokens:
                usage.append(f" · {format_tokens(u.cache_read_tokens)} cache", style=_ui.MUTE)
            usage.append(f"\ncusto {cr.label}", style=_ui.MAGENTA)
            cards.append(_ui.panel(usage, title="Uso", accent=_ui.CYAN))
    except Exception:  # noqa: BLE001
        pass

    console.print(_ui.grid(cards, width=console.width))
    console.print(_ui.footer("Próximos passos:", [
        ("okami chat", "conversa no terminal"),
        ("okami doctor", "diagnóstico de config/chaves/conectividade"),
        ("okami policy check --strict", "prontidão de GA"),
    ]))
    console.print()


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


def _version_cb(value: bool) -> None:
    if value:
        console.print(__version__)
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    _version: bool = typer.Option(False, "--version", "-V", help="Mostra a versão e sai.",
                                  callback=_version_cb, is_eager=True),
) -> None:
    """Okami Agent — CLI. Sem comando, mostra a visão geral."""
    if ctx.invoked_subcommand is None:
        help_cmd()


if __name__ == "__main__":
    app()
