"""Assistente de configuração (`okami setup`) + auto-detecção de ambiente."""
from __future__ import annotations

import typer
from okami.config import config_dir
from okami.i18n import t as _tr
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _build_memory_block, _pick_model, _provider_add_flow, _SETUP_SECTIONS, _slug, _ensure_agent,
)
from okami.i18n import t


@app.command(help=_tr("cli.setup", _default="Configuration wizard (arrow menus) — providers, login, memory, identity, channel."))
def setup(
    section: str = typer.Argument(None, help=_tr("cli.setup.section", _default="provider|default|memory|identity|channel (empty = full wizard)")),
    memory: str = typer.Option(None, "--memory", help=_tr("cli.setup.memory", _default="fts5 | holographic | holographic+honcho (non-interactive).")),
    honcho_url: str = typer.Option(None, "--honcho-url"),
    honcho_key: str = typer.Option(None, "--honcho-key"),
    embedder_url: str = typer.Option(None, "--embedder-url"),
    embedder_model: str = typer.Option(None, "--embedder-model"),
) -> None:
    """Configuration wizard (arrow menus) — providers, login, memory, identity, channel.

    No editing YAML by hand. `okami setup provider` jumps straight to a section. `okami setup --memory fts5`
    is the non-interactive shortcut (memory only). `hermes setup` style."""
    import yaml as _yaml

    from okami import menu

    # --- atalho não-interativo: só memória (compat: scripts/CI) ---------------
    if memory:
        mem = _build_memory_block(memory, honcho_url, honcho_key, embedder_url, embedder_model)
        (config_dir() / "okami.local.yaml").write_text(
            _yaml.safe_dump({"memory": mem}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        console.print(t("setup.local_written", _default="[green]✓ okami.local.yaml written[/green] (backend={backend})",
                        backend=mem['backend']))
        return

    if section and section not in _SETUP_SECTIONS:
        console.print(t("setup.invalid_section", _default="[red]invalid section:[/red] {section} (use: {sections})",
                        section=section, sections=', '.join(_SETUP_SECTIONS)))
        raise typer.Exit(1)

    cfg_path = config_dir() / "okami.yaml"
    fresh = not cfg_path.exists()
    local: dict = {}
    if (config_dir() / "okami.local.yaml").exists():
        local = _yaml.safe_load((config_dir() / "okami.local.yaml").read_text(encoding="utf-8")) or {}

    def save_local() -> None:
        (config_dir() / "okami.local.yaml").write_text(
            _yaml.safe_dump(local, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # Painel de localização (estilo Hermes "Configuration Location")
    from rich.panel import Panel

    from okami.home import agents_dir
    loc = config_dir()
    head = t("setup.panel.head", _default="[bold #ff7527]🐺 Okami — configuration[/]")
    if not fresh:
        head += "\n" + t("setup.panel.already",
                         _default="[green]✓ you already have Okami configured[/] [dim](Enter keeps the current value)[/dim]")
    console.print(Panel(t("setup.panel.body",
                          _default="{head}\n\n[dim]okami.yaml:[/dim] {yaml}\n"
                                   "[dim]overrides:[/dim] {local}\n[dim]secrets (.env):[/dim] {env}\n"
                                   "[dim]agents:[/dim]   {agents}\n\n"
                                   "[dim]Jump to a section: okami setup "
                                   "provider|memory|agent|channel|voice|approvals|posture|learning|persona[/dim]",
                          head=head, yaml=loc / 'okami.yaml', local=loc / 'okami.local.yaml',
                          env=loc / '.env', agents=agents_dir()),
                        border_style="#ff7527", title="Configuration"))

    def step_provider() -> None:
        from okami.config import load_raw
        if not cfg_path.exists():
            res = _provider_add_flow()
            if not res:
                return
            pid, pdict = res
            cfg_path.write_text(_yaml.safe_dump({"default_provider": pid, "providers": {pid: pdict}},
                                                allow_unicode=True, sort_keys=False), encoding="utf-8")
            console.print(t("setup.provider.created",
                            _default="[green]✓ okami.yaml created[/green] · provider [bold]{pid}[/bold]", pid=pid))
            return
        raw, _ = load_raw()
        provs = raw.get("providers") or {}
        cur = local.get("default_provider") or raw.get("default_provider")
        choices = [(n, n, str((provs[n] or {}).get("model", ""))) for n in provs]
        choices.append(("__add__", t("setup.provider.add_label", _default="➕ add a new provider"),
                        t("setup.provider.add_hint", _default="from the catalog (Codex, OpenAI, etc.)")))
        pick = menu.select(t("setup.provider.prompt", _default="Default provider"), choices, default=cur)
        if pick == "__add__":
            res = _provider_add_flow()
            if res:
                pid, pdict = res
                raw2 = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                raw2.setdefault("providers", {})[pid] = pdict
                cfg_path.write_text(_yaml.safe_dump(raw2, allow_unicode=True, sort_keys=False), encoding="utf-8")
                console.print(t("setup.provider.added", _default="[green]✓ provider '{pid}' added[/green]", pid=pid))
                if menu.confirm(t("setup.provider.use_as_default", _default="Use '{pid}' as default?", pid=pid),
                                default=True):
                    local["default_provider"] = pid
        elif pick and pick != cur:
            local["default_provider"] = pick
        save_local()
        console.print(t("setup.provider.default", _default="[green]✓ default:[/green] {value}",
                        value=local.get('default_provider', cur)))
        # Esforço de raciocínio (think) do provider default — só faz sentido em modelo reasoning.
        dp = local.get("default_provider") or cur
        if dp and dp in provs:
            cur_eff = (provs[dp] or {}).get("reasoning_effort", "")
            eff = menu.select(t("setup.think.prompt", _default="Think (reasoning effort) for '{dp}'", dp=dp), [
                ("", t("setup.think.model_default", _default="model default"), ""),
                ("minimal", "minimal", t("setup.think.minimal", _default="fast/cheap")),
                ("low", "low", ""), ("medium", "medium", ""),
                ("high", "high", t("setup.think.high", _default="more reasoning, slower/pricier"))], default=cur_eff)
            if eff != cur_eff:
                raw2 = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                pd = raw2.setdefault("providers", {}).setdefault(dp, {})
                pd["reasoning_effort"] = eff if eff else None
                if not eff:
                    pd.pop("reasoning_effort", None)
                cfg_path.write_text(_yaml.safe_dump(raw2, allow_unicode=True, sort_keys=False),
                                    encoding="utf-8")
                console.print(t("setup.think.set", _default="[green]✓ think:[/green] {value}",
                                value=eff or 'default'))

    def step_login() -> None:
        try:
            save_local()
            cfg = _load()
            default_prov = cfg.default_provider
            pc = cfg.provider(default_prov)
            if pc.ready:
                return
            if pc.transport in ("codex_oauth", "minimax_oauth") and \
                    menu.confirm(t("setup.login.confirm",
                                   _default="Provider '{prov}' needs login. Do it now?", prov=default_prov),
                                 default=True):
                from okami.llm import oauth
                if pc.transport == "codex_oauth":
                    oauth.codex_device_login(lambda m: console.print(m))
                elif pc.oauth:
                    oauth.device_login(default_prov, pc.oauth, lambda m: console.print(m))
                console.print(t("setup.login.ok", _default="[green]✓ login {prov} ok[/green]", prov=default_prov))
            elif pc.transport == "claude_cli":
                console.print(t("setup.login.claude_cli",
                                _default="[yellow]'{prov}' uses the `claude` CLI — install it and run `claude login`.[/yellow]",
                                prov=default_prov))
        except Exception as e:  # noqa: BLE001 — login é opcional
            console.print(t("setup.login.skipped", _default="[yellow]login skipped:[/yellow] {error}", error=e))

    def step_memory() -> None:
        cur = (local.get("memory") or {}).get("backend")
        cur_key = {"sqlite-fts5": "fts5", "holographic": "holographic"}.get(
            cur if isinstance(cur, str) else "", "holographic+honcho" if cur else None)
        pick = menu.select(t("setup.memory.prompt", _default="Memory"), [
            ("fts5", "FTS5", t("setup.memory.fts5", _default="lightweight, public / weak hardware")),
            ("holographic", "Holographic",
             t("setup.memory.holographic", _default="local, native, no embedding server")),
            ("holographic+honcho", "Holographic + Honcho",
             t("setup.memory.holographic_honcho", _default="daily-driver (local + remote user-model)")),
        ], default=cur_key or "fts5")
        local["memory"] = _build_memory_block(pick, honcho_url=honcho_url, honcho_key=honcho_key)
        save_local()
        console.print(t("setup.memory.set", _default="[green]✓ memory:[/green] {backend}",
                        backend=local['memory']['backend']))

    def step_agent() -> None:
        # Cria um AGENTE de verdade (agents/<id>/ com identidade + memória próprias). Sem nome →
        # vira o agente padrão "okami". Conforme cria mais agentes, cada um ganha sua pasta.
        name = menu.text(t("setup.agent.prompt", _default="Agent name (empty = default agent)"), default="Okami")
        agent_id = _slug(name) or "okami"
        created = _ensure_agent(agent_id, name=name)
        agents = dict(local.get("agents") or {})
        agents["default"] = agent_id                  # roteamento + `okami chat` usam este
        local["agents"] = agents
        save_local()
        verb = t("setup.agent.created", _default="created") if created \
            else t("setup.agent.existed", _default="already existed")
        from okami.home import agents_dir
        d = (agents_dir() / agent_id).resolve()
        console.print(t("setup.agent.done",
                        _default="[green]✓ agent '{agent_id}' {verb}[/green]\n[dim]   {dir}[/dim]\n"
                                 "[dim]   own SOUL/VOICE/PERSONA + sessions/memory[/dim]",
                        agent_id=agent_id, verb=verb, dir=d))

    def step_channel() -> None:
        agent_id = (local.get("agents") or {}).get("default") or "okami"
        if menu.confirm(t("setup.channel.confirm",
                          _default="Set up a Telegram bot now? (otherwise, use the terminal chat)"), default=False):
            token = menu.text(t("setup.channel.token", _default="Bot token (@BotFather)"), password=True)
            _ensure_agent(agent_id, telegram_token=token)   # anexa a token ao agente default
            console.print(t("setup.channel.linked",
                            _default="[green]✓ Telegram linked to agent '{agent_id}'[/green] — start it with: okami gateway",
                            agent_id=agent_id))
        else:
            console.print(t("setup.channel.skip", _default="[dim]all good — talk to it via: okami chat[/dim]"))

    def step_voice() -> None:
        cur = local.get("voice") or {}
        cur_mode = ("both" if (cur.get("tts") or {}).get("enabled")
                    else "stt" if (cur.get("stt") or {}).get("enabled") else "off")
        pick = menu.select(t("setup.voice.prompt", _default="Voice (audio in chat/Telegram)?"), [
            ("off", t("setup.voice.off_label", _default="Off"),
             t("setup.voice.off_hint", _default="text only (default)")),
            ("stt", t("setup.voice.stt_label", _default="Listen"),
             t("setup.voice.stt_hint", _default="transcribes incoming audio — local Whisper")),
            ("both", t("setup.voice.both_label", _default="Listen + speak"),
             t("setup.voice.both_hint", _default="transcribes and replies with audio — Edge TTS")),
        ], default=cur_mode)
        if pick == "off":
            local.pop("voice", None)
        else:
            v = {"stt": {"enabled": True, "model": "base"}}
            if pick == "both":
                v["tts"] = {"enabled": True, "backend": "edge", "voice": "pt-BR-AntonioNeural"}
            local["voice"] = v
            console.print(t("setup.voice.requires",
                            _default=r'[dim]requires: pip install "okami-agent\[voice]"[/dim]'))
        save_local()
        console.print(t("setup.voice.set", _default="[green]✓ voice:[/green] {value}", value=pick))

    def step_approvals() -> None:
        cur = (local.get("approvals") or {}).get("mode", "manual")
        pick = menu.select(t("setup.approvals.prompt",
                             _default="Approval for sensitive actions (.env, git push, rm -rf)?"), [
            ("manual", t("setup.approvals.manual_label", _default="Manual"),
             t("setup.approvals.manual_hint", _default="asks before each sensitive action (safest)")),
            ("smart", t("setup.approvals.smart_label", _default="Smart"),
             t("setup.approvals.smart_hint", _default="auto-approves low risk, asks for the rest")),
            ("yolo", "YOLO", t("setup.approvals.yolo_hint", _default="auto-approves everything — careful")),
        ], default=cur)
        local["approvals"] = {**(local.get("approvals") or {}), "mode": pick}
        save_local()
        console.print(t("setup.approvals.set", _default="[green]✓ approval:[/green] {value}", value=pick))

    def step_posture() -> None:
        sb = dict(local.get("sandbox") or {})
        cur = "prod" if sb.get("profile") == "hardened-strict" else "dev"
        pick = menu.select(t("setup.posture.prompt", _default="Where will Okami run?"), [
            ("dev", t("setup.posture.dev_label", _default="Local / dev"),
             t("setup.posture.dev_hint",
               _default="your machine; exposed surface degrades to local (warning, no block)")),
            ("prod", t("setup.posture.prod_label", _default="Public gateway / production"),
             t("setup.posture.prod_hint", _default="STRICT isolation (hardened-strict) — requires Docker")),
        ], default=cur)
        if pick == "prod":
            sb["profile"] = "hardened-strict"            # = okami harden (postura nomeada de GA)
            sb.pop("require_isolation", None)
            local["sandbox"] = sb
            save_local()
            console.print(t("setup.posture.prod_on",
                            _default="[green]✓ production: hardened-strict profile on[/green] "
                                     "[dim](exposed surface without Docker → run_shell/process DISABLED, fail-closed)[/dim]"))
            from okami.core.sandbox import SandboxPolicy
            if SandboxPolicy.from_config({"backend": "auto"}).effective_backend() != "docker":
                console.print(t("setup.posture.no_docker",
                                _default="[yellow]   Docker NOT detected[/yellow] — install/open Docker before exposing publicly."))
        else:
            if sb.get("profile") == "hardened-strict":
                sb.pop("profile", None)
            if sb:
                local["sandbox"] = sb
            else:
                local.pop("sandbox", None)
            save_local()
            console.print(t("setup.posture.dev_on",
                            _default="[dim]✓ dev: local fences (fast). Before exposing publicly: okami harden[/dim]"))

    def step_learning() -> None:
        cur = local.get("learning") or {}
        skill = menu.confirm(t("setup.learning.skill",
                               _default="Auto-skill? (distills skills from successful tasks, scanned for safety)"),
                             default=bool(cur.get("auto_skill")))
        tune = menu.confirm(t("setup.learning.tune",
                              _default="Auto-tune? (calibrates the model's capability profile from usage stats)"),
                            default=bool(cur.get("auto_tune")))
        local["learning"] = {**cur, "auto_skill": skill, "auto_tune": tune}
        save_local()
        console.print(t("setup.learning.set",
                        _default="[green]✓ learning:[/green] auto-skill={skill} · auto-tune={tune}",
                        skill='on' if skill else 'off', tune='on' if tune else 'off'))

    def step_persona() -> None:
        cur = local.get("persona") or {}
        observe = menu.confirm(t("setup.persona.observe",
                                 _default="Evolving persona? (learns your style — slang, nickname, tone — and adapts on its own)"),
                               default=cur.get("observe", True))
        local["persona"] = {**cur, "observe": observe}
        save_local()
        console.print(t("setup.persona.set", _default="[green]✓ evolving persona:[/green] {value}",
                        value='on' if observe else 'off'))

    def step_quick() -> None:
        """RÁPIDO (estilo Hermes/OpenClaw): detecta o que você já tem → provider + modelo → agente.
        2-3 decisões e tá conversando."""
        from okami.provider_catalog import preset
        raw = (_yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}) or {}
        console.print(t("setup.quick.searching",
                        _default="[dim]🔍 looking for available providers (local servers, OAuth, keys)…[/dim]"))
        from okami import cli as _cli  # lookup via pacote → respeita monkeypatch dos testes
        detected = _cli._detect_environment(existing=raw.get("providers"))
        choices = [(d.key, d.label, "") for d in detected]
        choices.append(("__other__", t("setup.quick.other_label", _default="another provider (full catalog)"),
                        "Codex, OpenAI, OpenRouter…"))
        if detected:
            console.print(t("setup.quick.found", _default="[green]✓ found {n} provider(s) ready[/green]",
                            n=len(detected)))
        pick = menu.select(t("setup.quick.prompt", _default="Which one to use?"), choices,
                           default=(detected[0].key if detected else "__other__"))
        if not pick:
            return
        if pick == "__other__":
            res = _provider_add_flow()
            if not res:
                return
            pid, pdict = res
        else:                                     # detectado → só falta escolher o modelo
            d = next(x for x in detected if x.key == pick)
            p = preset(d.key)
            pdict = dict(d.pdict)
            _pick_model(pdict, model_prefix=(p.model_prefix if p else ""), catalog=(p.models if p else []))
            if p and p.note:
                pdict["notes"] = p.note
            pid = pick
        raw.setdefault("providers", {})
        raw["providers"][pid] = {**(raw["providers"].get(pid) or {}), **pdict}   # merge, não clobbera
        raw["default_provider"] = pid
        cfg_path.write_text(_yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
        local["default_provider"] = pid
        save_local()
        console.print(t("setup.quick.provider_set",
                        _default="[green]✓ provider:[/green] {pid} · [bold]{model}[/bold]",
                        pid=pid, model=pdict.get('model')))
        step_login()
        _ensure_agent("okami", name="Okami")      # agente padrão (sem perguntar no rápido)
        local.setdefault("agents", {})["default"] = "okami"
        save_local()
        from okami.home import agents_dir
        console.print(t("setup.quick.agent_default",
                        _default="[green]✓ default agent 'okami'[/green] [dim]({dir})[/dim]",
                        dir=(agents_dir() / 'okami').resolve()))

    steps = {"provider": step_provider, "default": step_provider, "memory": step_memory,
             "agent": step_agent, "identity": step_agent, "channel": step_channel,
             "voice": step_voice, "approvals": step_approvals, "security": step_approvals,
             "posture": step_posture, "production": step_posture,
             "learning": step_learning, "persona": step_persona}
    if section:                                   # pulo direto pra uma seção (sem fork)
        steps[section]()
        if section in ("provider", "default"):
            step_login()
        return

    # FORK Rápido vs Completo no PRIMEIRO prompt (a maior melhoria, validada em Hermes E OpenClaw)
    mode = menu.select(t("setup.mode.prompt", _default="How to configure?"), [
        ("quick", t("setup.mode.quick_label", _default="Quick"),
         t("setup.mode.quick_hint", _default="provider + model (recommended) — detects what you already have")),
        ("full", t("setup.mode.full_label", _default="Full"),
         t("setup.mode.full_hint", _default="provider · memory · identity · channel · voice · security · learning")),
    ], default="quick")
    if mode == "full":
        for fn in (step_provider, step_login, step_memory, step_agent, step_channel,
                   step_voice, step_approvals, step_posture, step_learning, step_persona):
            fn()
    else:
        step_quick()

    default_agent = (local.get("agents") or {}).get("default", "okami")
    console.print("\n" + t("setup.done.header",
                           _default="[bold green]✓ all set![/bold green]  Next steps:"))
    console.print(t("setup.done.chat",
                    _default="  [bold]okami chat[/bold]     — chat with the agent '{agent}'", agent=default_agent))
    console.print(t("setup.done.doctor",
                    _default="  [bold]okami doctor[/bold]   — checks keys and connectivity"))
    if mode == "quick":
        console.print(t("setup.done.tweak",
                        _default="  [dim]tweak more:[/dim] okami setup memory · okami setup channel · okami provider add"))
    else:
        console.print(t("setup.done.add_provider",
                        _default="  [bold]okami provider add[/bold]  — add another model whenever you want"))


