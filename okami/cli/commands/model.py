"""`okami model` — troca UNIFICADA de provider/modelo por alias (owner: "não consigo trocar fácil").

Fonte única de resolução: okami/llm/model_aliases.py. Este comando é só UI em cima dela — mesma regra
vale pro `/model` do gateway (okami/gateway/endpoint_commands.py) e pro `-p/-m` da CLI (chat.py).

Implementado como UM comando plano (não um Typer sub-group com Argument + subcommand): misturar um
Argument posicional com subcommands num Typer/Click Group faz o parser consumir o 1º token pro
Argument ANTES de resolver o subcommand (`okami model list` nunca chegava no subcommand `list`).
`list` é tratado como palavra reservada do próprio comando — nenhum provider/alias real se chama assim."""
from __future__ import annotations

import json as _json

import typer
from okami.cli._app import app, console
from okami.cli._shared import _load, _write_model_override
from okami.i18n import t as _tr
from okami.llm.model_aliases import ModelAliasError, full_model_string, known_aliases, resolve


def _effective(cfg) -> tuple[str, str, str]:
    """(provider, modelo efetivo, fonte do override) — SEM sessão (CLI não tem sessão de gateway).
    Fonte: 'okami.local.yaml' se o local overridou o provider/model, senão 'okami.yaml' (default)."""
    import yaml as _yaml
    from okami.config import config_dir
    pid = cfg.default_provider
    pc = cfg.provider(pid)
    local_path = config_dir() / "okami.local.yaml"
    source = "okami.yaml"
    if local_path.exists():
        local_raw = _yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}
        if local_raw.get("default_provider") == pid or (local_raw.get("providers") or {}).get(pid):
            source = "okami.local.yaml"
    return pid, pc.model, source


@app.command("model", help=_tr("cli.model", _default="Switch provider/model by alias (sonnet/opus/codex/fast/smart/…)."))
def model_cmd(
    token: str = typer.Argument(None, help=_tr(
        "cli.model.token",
        _default="Alias/provider/model ('list' = table, empty = interactive picker).")),
    save: bool = typer.Option(True, "--save/--no-save", help=_tr(
        "cli.model.save", _default="Persist as the new default in okami.local.yaml (default: yes).")),
    as_json: bool = typer.Option(False, "--json", help=_tr(
        "cli.model.json", _default="With 'list': JSON output.")),
) -> None:
    """`okami model` (sem args) → mostra o efetivo + menu de seta.
    `okami model <token>` → resolve e grava. `okami model list [--json]` → tabela de aliases."""
    cfg = _load()
    if token == "list":
        _list(cfg, as_json=as_json)
        return
    if token:
        _apply(cfg, token, save=save)
        return
    pid, model, source = _effective(cfg)
    console.print(f"🧠 [bold]{pid}[/bold] · {model}  [dim]({source})[/dim]")
    from okami import menu
    # Picker dos MODELOS REAIS de cada provider CONFIGURADO (não aliases abstratos) — o dono quer escolher
    # entre as contas/CLIs/APIs que ELE tem, com os modelos que cada uma expõe. Marca o atual e o auth.
    from okami.cli.commands.config import _provider_auth_state
    rows = []
    cur_full = f"{pid}/{model}" if model else pid
    for provider in (cfg.providers or {}):
        pc = cfg.providers.get(provider)
        if pc is None:
            continue
        _method, _kenv, authed = _provider_auth_state(cfg, provider)
        auth_badge = "✓ auth" if authed else "✗ falta login"
        tier = getattr(pc, "tier", "?") or "?"
        models = list(getattr(pc, "models", None) or [])
        if not models:                                   # provider sem lista → usa o modelo default dele
            dm = getattr(pc, "model", "") or ""
            models = [dm] if dm else []
        for m in models:
            token = f"{provider}/{m}"                     # resolve() aceita '<provider>/<model>'
            here = " ← atual" if (token == cur_full or (m == model and provider == pid)) else ""
            label = f"{provider:<9} · {m}"
            rows.append((token, label, f"tier={tier} · {auth_badge}{here}"))
    if not rows:                                         # fallback: sem modelos reais → volta pros aliases
        for alias, provider, hint in known_aliases(cfg):
            rows.append((alias, f"{alias} → {provider}", ""))
    picked = menu.select("Trocar pra qual modelo?", rows, default=cur_full)
    if not picked:
        console.print("[dim]cancelado.[/dim]")
        raise typer.Exit(1)
    _apply(cfg, picked, save=True)


def _apply(cfg, token: str, *, save: bool) -> None:
    try:
        provider, model = resolve(cfg, token)
    except ModelAliasError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1) from None
    full_model = full_model_string(cfg, provider, model) if model else None
    if save:
        _write_model_override(provider, full_model)
    pc = cfg.providers[provider]
    ready = "" if pc.ready else f" [yellow]⚠ não autenticado — okami login {provider}[/yellow]"
    console.print(f"[green]✓[/green] provider [bold]{provider}[/bold] · modelo "
                  f"[bold]{full_model or pc.model}[/bold]{ready}")


def _list(cfg, *, as_json: bool) -> None:
    rows = []
    seen: set[str] = set()
    for alias, provider, _hint in known_aliases(cfg):
        if alias in seen:
            continue
        seen.add(alias)
        try:
            resolved_provider, resolved_model = resolve(cfg, alias)
        except ModelAliasError:
            resolved_provider, resolved_model = provider, None
        pc = cfg.providers.get(resolved_provider)
        rows.append({
            "alias": alias, "provider": resolved_provider,
            "model": resolved_model or (pc.model if pc else None),
            "tier": pc.tier if pc else None,
            "ready": bool(pc.ready) if pc else False,
        })
    if as_json:
        console.print(_json.dumps(rows, ensure_ascii=False, indent=2))
        return
    for r in rows:
        mark = "[green]✓[/green]" if r["ready"] else "[dim]…[/dim]"
        console.print(f"  {mark} [bold]{r['alias']:<10}[/bold] → {r['provider']:<12} "
                      f"{r['model'] or '':<28} [dim]tier={r['tier']}[/dim]")
