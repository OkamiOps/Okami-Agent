"""Assistente de configuração (`okami setup`) + auto-detecção de ambiente."""
from __future__ import annotations

import typer
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _build_memory_block, _pick_model, _provider_add_flow, _SETUP_SECTIONS, _slug, _ensure_agent,
)


@app.command()
def setup(
    section: str = typer.Argument(None, help="provider|default|memory|identity|channel (vazio = wizard completo)"),
    memory: str = typer.Option(None, "--memory", help="fts5 | holographic | holographic+honcho (não-interativo)."),
    honcho_url: str = typer.Option(None, "--honcho-url"),
    honcho_key: str = typer.Option(None, "--honcho-key"),
    embedder_url: str = typer.Option(None, "--embedder-url"),
    embedder_model: str = typer.Option(None, "--embedder-model"),
) -> None:
    """Assistente de configuração (menus de seta) — providers, login, memória, identidade, canal.

    Sem editar YAML na mão. `okami setup provider` pula direto pra uma seção. `okami setup --memory fts5`
    é o atalho não-interativo (só memória). Estilo `hermes setup`."""
    import yaml as _yaml

    from okami import menu

    # --- atalho não-interativo: só memória (compat: scripts/CI) ---------------
    if memory:
        mem = _build_memory_block(memory, honcho_url, honcho_key, embedder_url, embedder_model)
        Path("okami.local.yaml").write_text(
            _yaml.safe_dump({"memory": mem}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        console.print(f"[green]✓ okami.local.yaml gravado[/green] (backend={mem['backend']})")
        return

    if section and section not in _SETUP_SECTIONS:
        console.print(f"[red]seção inválida:[/red] {section} (use: {', '.join(_SETUP_SECTIONS)})")
        raise typer.Exit(1)

    cfg_path = Path("okami.yaml")
    fresh = not cfg_path.exists()
    local: dict = {}
    if Path("okami.local.yaml").exists():
        local = _yaml.safe_load(Path("okami.local.yaml").read_text(encoding="utf-8")) or {}

    def save_local() -> None:
        Path("okami.local.yaml").write_text(
            _yaml.safe_dump(local, allow_unicode=True, sort_keys=False), encoding="utf-8")

    # Painel de localização (estilo Hermes "Configuration Location")
    from rich.panel import Panel
    loc = Path.cwd()
    head = "[bold #ff7527]🐺 Okami — configuração[/]"
    if not fresh:
        head += "\n[green]✓ você já tem o Okami configurado[/] [dim](Enter mantém o valor atual)[/dim]"
    console.print(Panel(f"{head}\n\n[dim]okami.yaml:[/dim] {loc / 'okami.yaml'}\n"
                        f"[dim]overrides:[/dim] {loc / 'okami.local.yaml'}\n[dim]segredos (.env):[/dim] {loc / '.env'}\n"
                        f"[dim]agentes:[/dim]   {loc / 'agents'}\n\n"
                        "[dim]Pule pra uma seção: okami setup "
                        "provider|memory|agent|channel|voice|approvals|learning|persona[/dim]",
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
            console.print(f"[green]✓ okami.yaml criado[/green] · provider [bold]{pid}[/bold]")
            return
        raw, _ = load_raw()
        provs = raw.get("providers") or {}
        cur = local.get("default_provider") or raw.get("default_provider")
        choices = [(n, n, str((provs[n] or {}).get("model", ""))) for n in provs]
        choices.append(("__add__", "➕ adicionar novo provider", "do catálogo (Codex, OpenAI, etc.)"))
        pick = menu.select("Provider default", choices, default=cur)
        if pick == "__add__":
            res = _provider_add_flow()
            if res:
                pid, pdict = res
                raw2 = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                raw2.setdefault("providers", {})[pid] = pdict
                cfg_path.write_text(_yaml.safe_dump(raw2, allow_unicode=True, sort_keys=False), encoding="utf-8")
                console.print(f"[green]✓ provider '{pid}' adicionado[/green]")
                if menu.confirm(f"Usar '{pid}' como default?", default=True):
                    local["default_provider"] = pid
        elif pick and pick != cur:
            local["default_provider"] = pick
        save_local()
        console.print(f"[green]✓ default:[/green] {local.get('default_provider', cur)}")
        # Esforço de raciocínio (think) do provider default — só faz sentido em modelo reasoning.
        dp = local.get("default_provider") or cur
        if dp and dp in provs:
            cur_eff = (provs[dp] or {}).get("reasoning_effort", "")
            eff = menu.select(f"Think (esforço de raciocínio) do '{dp}'", [
                ("", "default do modelo", ""), ("minimal", "minimal", "rápido/barato"),
                ("low", "low", ""), ("medium", "medium", ""),
                ("high", "high", "mais raciocínio, mais lento/caro")], default=cur_eff)
            if eff != cur_eff:
                raw2 = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                pd = raw2.setdefault("providers", {}).setdefault(dp, {})
                pd["reasoning_effort"] = eff if eff else None
                if not eff:
                    pd.pop("reasoning_effort", None)
                cfg_path.write_text(_yaml.safe_dump(raw2, allow_unicode=True, sort_keys=False),
                                    encoding="utf-8")
                console.print(f"[green]✓ think:[/green] {eff or 'default'}")

    def step_login() -> None:
        try:
            save_local()
            cfg = _load()
            default_prov = cfg.default_provider
            pc = cfg.provider(default_prov)
            if pc.ready:
                return
            if pc.transport in ("codex_oauth", "minimax_oauth") and \
                    menu.confirm(f"Provider '{default_prov}' precisa de login. Fazer agora?", default=True):
                from okami.llm import oauth
                if pc.transport == "codex_oauth":
                    oauth.codex_device_login(lambda m: console.print(m))
                elif pc.oauth:
                    oauth.device_login(default_prov, pc.oauth, lambda m: console.print(m))
                console.print(f"[green]✓ login {default_prov} ok[/green]")
            elif pc.transport == "claude_cli":
                console.print(f"[yellow]'{default_prov}' usa o CLI `claude` — instale e rode `claude login`.[/yellow]")
        except Exception as e:  # noqa: BLE001 — login é opcional
            console.print(f"[yellow]login pulado:[/yellow] {e}")

    def step_memory() -> None:
        cur = (local.get("memory") or {}).get("backend")
        cur_key = {"sqlite-fts5": "fts5", "holographic": "holographic"}.get(
            cur if isinstance(cur, str) else "", "holographic+honcho" if cur else None)
        pick = menu.select("Memória", [
            ("fts5", "FTS5", "leve, público / hardware fraco"),
            ("holographic", "Holographic", "local, nativo, sem servidor de embedding"),
            ("holographic+honcho", "Holographic + Honcho", "daily-driver (local + user-model remoto)"),
        ], default=cur_key or "fts5")
        local["memory"] = _build_memory_block(pick, honcho_url=honcho_url, honcho_key=honcho_key)
        save_local()
        console.print(f"[green]✓ memória:[/green] {local['memory']['backend']}")

    def step_agent() -> None:
        # Cria um AGENTE de verdade (agents/<id>/ com identidade + memória próprias). Sem nome →
        # vira o agente padrão "okami". Conforme cria mais agentes, cada um ganha sua pasta.
        name = menu.text("Nome do agente (vazio = agente padrão)", default="Okami")
        agent_id = _slug(name) or "okami"
        created = _ensure_agent(agent_id, name=name)
        agents = dict(local.get("agents") or {})
        agents["default"] = agent_id                  # roteamento + `okami chat` usam este
        local["agents"] = agents
        save_local()
        verb = "criado" if created else "já existia"
        d = (Path("agents") / agent_id).resolve()
        console.print(f"[green]✓ agente '{agent_id}' {verb}[/green]\n[dim]   {d}[/dim]\n"
                      f"[dim]   SOUL/VOICE/PERSONA + sessões/memória próprias[/dim]")

    def step_channel() -> None:
        agent_id = (local.get("agents") or {}).get("default") or "okami"
        if menu.confirm("Configurar um bot do Telegram agora? (senão, use o chat do terminal)", default=False):
            token = menu.text("Token do bot (@BotFather)", password=True)
            _ensure_agent(agent_id, telegram_token=token)   # anexa a token ao agente default
            console.print(f"[green]✓ Telegram ligado no agente '{agent_id}'[/green] — suba com: okami gateway")
        else:
            console.print("[dim]beleza — fale com ele por: okami chat[/dim]")

    def step_voice() -> None:
        cur = local.get("voice") or {}
        cur_mode = ("both" if (cur.get("tts") or {}).get("enabled")
                    else "stt" if (cur.get("stt") or {}).get("enabled") else "off")
        pick = menu.select("Voz (áudio no chat/Telegram)?", [
            ("off", "Desligada", "só texto (default)"),
            ("stt", "Ouvir", "transcreve áudio recebido — Whisper local"),
            ("both", "Ouvir + falar", "transcreve e responde em áudio — Edge TTS"),
        ], default=cur_mode)
        if pick == "off":
            local.pop("voice", None)
        else:
            v = {"stt": {"enabled": True, "model": "base"}}
            if pick == "both":
                v["tts"] = {"enabled": True, "backend": "edge", "voice": "pt-BR-AntonioNeural"}
            local["voice"] = v
            console.print(r'[dim]requer: pip install "okami-agent\[voice]"[/dim]')
        save_local()
        console.print(f"[green]✓ voz:[/green] {pick}")

    def step_approvals() -> None:
        cur = (local.get("approvals") or {}).get("mode", "manual")
        pick = menu.select("Aprovação de ações sensíveis (.env, git push, rm -rf)?", [
            ("manual", "Manual", "pergunta antes de cada ação sensível (mais seguro)"),
            ("smart", "Inteligente", "auto-aprova risco baixo, pergunta o resto"),
            ("yolo", "YOLO", "auto-aprova tudo — cuidado"),
        ], default=cur)
        local["approvals"] = {**(local.get("approvals") or {}), "mode": pick}
        save_local()
        console.print(f"[green]✓ aprovação:[/green] {pick}")

    def step_learning() -> None:
        cur = local.get("learning") or {}
        skill = menu.confirm("Auto-skill? (destila skills de tarefas bem-sucedidas, escaneadas p/ segurança)",
                             default=bool(cur.get("auto_skill")))
        tune = menu.confirm("Auto-tune? (calibra o capability profile do modelo pelos stats de uso)",
                            default=bool(cur.get("auto_tune")))
        local["learning"] = {**cur, "auto_skill": skill, "auto_tune": tune}
        save_local()
        console.print(f"[green]✓ aprendizado:[/green] auto-skill={'on' if skill else 'off'} · "
                      f"auto-tune={'on' if tune else 'off'}")

    def step_persona() -> None:
        cur = local.get("persona") or {}
        observe = menu.confirm("Persona evolutiva? (aprende seu jeito — palavrão, apelido, tom — e adapta sozinho)",
                               default=cur.get("observe", True))
        local["persona"] = {**cur, "observe": observe}
        save_local()
        console.print(f"[green]✓ persona evolutiva:[/green] {'on' if observe else 'off'}")

    def step_quick() -> None:
        """RÁPIDO (estilo Hermes/OpenClaw): detecta o que você já tem → provider + modelo → agente.
        2-3 decisões e tá conversando."""
        from okami.provider_catalog import preset
        raw = (_yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}) or {}
        console.print("[dim]🔍 procurando providers disponíveis (servidores locais, OAuth, chaves)…[/dim]")
        from okami import cli as _cli  # lookup via pacote → respeita monkeypatch dos testes
        detected = _cli._detect_environment(existing=raw.get("providers"))
        choices = [(d.key, d.label, "") for d in detected]
        choices.append(("__other__", "outro provider (catálogo completo)", "Codex, OpenAI, OpenRouter…"))
        if detected:
            console.print(f"[green]✓ encontrei {len(detected)} provider(es) prontos[/green]")
        pick = menu.select("Qual usar?", choices, default=(detected[0].key if detected else "__other__"))
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
        console.print(f"[green]✓ provider:[/green] {pid} · [bold]{pdict.get('model')}[/bold]")
        step_login()
        _ensure_agent("okami", name="Okami")      # agente padrão (sem perguntar no rápido)
        local.setdefault("agents", {})["default"] = "okami"
        save_local()
        console.print(f"[green]✓ agente padrão 'okami'[/green] [dim]({(Path('agents') / 'okami').resolve()})[/dim]")

    steps = {"provider": step_provider, "default": step_provider, "memory": step_memory,
             "agent": step_agent, "identity": step_agent, "channel": step_channel,
             "voice": step_voice, "approvals": step_approvals, "security": step_approvals,
             "learning": step_learning, "persona": step_persona}
    if section:                                   # pulo direto pra uma seção (sem fork)
        steps[section]()
        if section in ("provider", "default"):
            step_login()
        return

    # FORK Rápido vs Completo no PRIMEIRO prompt (a maior melhoria, validada em Hermes E OpenClaw)
    mode = menu.select("Como configurar?", [
        ("quick", "Rápido", "provider + modelo (recomendado) — detecta o que você já tem"),
        ("full", "Completo", "provider · memória · identidade · canal · voz · segurança · aprendizado"),
    ], default="quick")
    if mode == "full":
        for fn in (step_provider, step_login, step_memory, step_agent, step_channel,
                   step_voice, step_approvals, step_learning, step_persona):
            fn()
    else:
        step_quick()

    default_agent = (local.get("agents") or {}).get("default", "okami")
    console.print("\n[bold green]✓ tudo pronto![/bold green]  Próximos passos:")
    console.print(f"  [bold]okami chat[/bold]     — conversa com o agente '{default_agent}'")
    console.print("  [bold]okami doctor[/bold]   — confere chaves e conectividade")
    if mode == "quick":
        console.print("  [dim]ajustar mais:[/dim] okami setup memory · okami setup channel · okami provider add")
    else:
        console.print("  [bold]okami provider add[/bold]  — adiciona outro modelo quando quiser")


