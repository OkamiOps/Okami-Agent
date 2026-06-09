"""Gerência de providers: provider add/list/remove/default/login/models."""
from __future__ import annotations

import typer
from okami.config import config_dir
from okami.i18n import t as _tr
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _provider_add_flow, _write_local,
)
from okami.cli.commands.basics import list_providers, login  # composição de comandos


provider_app = typer.Typer(invoke_without_command=True,
                           help=_tr("cli.provider", _default="LLM providers: add, list, remove, default, login."))
app.add_typer(provider_app, name="provider")


@provider_app.callback(invoke_without_command=True)
def provider_main(ctx: typer.Context) -> None:
    """`okami provider` SEM subcomando → lista os providers e a prontidão."""
    if ctx.invoked_subcommand is None:
        provider_list_cmd()


@provider_app.command("add", help=_tr("cli.provider.add", _default="Add a provider by picking a catalog preset (arrow menu). No YAML editing."))
def provider_add_cmd(
    default: bool = typer.Option(None, "--default/--no-default", help=_tr("cli.provider.add.default", _default="Set as the default provider.")),
) -> None:
    """Adiciona um provider escolhendo um preset do catálogo (menu de seta). Sem editar YAML."""
    import yaml as _yaml

    from okami import menu

    res = _provider_add_flow()
    if not res:
        console.print("[dim]cancelado.[/dim]")
        raise typer.Exit(1)
    pid, pdict = res
    cfg_path = config_dir() / "okami.yaml"
    raw = (_yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}) or {}
    provs = raw.setdefault("providers", {})
    if pid in provs:                               # NÃO clobbera: mescla sobre o existente (preserva extras)
        merged = dict(provs[pid] or {})
        merged.update(pdict)
        provs[pid] = merged
        console.print(f"[yellow]provider '{pid}' já existia — atualizado[/yellow] (config preservada + novos valores)")
    else:
        provs[pid] = pdict
        console.print(f"[green]✓ provider '{pid}' adicionado em okami.yaml[/green]")
    raw.setdefault("default_provider", pid)        # 1º provider de todos vira default automaticamente
    cfg_path.write_text(_yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")

    make_default = default if default is not None else menu.confirm(f"Usar '{pid}' como default?", default=False)
    if make_default:
        _write_local({"default_provider": pid})

    _provider_finish(pid, pdict, made_default=make_default)


def _provider_finish(pid: str, pdict: dict, *, made_default: bool) -> None:
    """Status de autenticação EXPLÍCITO + como usar. (compartilhado por provider add / setup)."""
    from okami import menu
    model = pdict.get("model", "?")
    try:
        pc = _load().provider(pid)
    except Exception as e:  # noqa: BLE001 — config inválida é erro de verdade, não engole
        console.print(f"[red]✗ não consegui carregar '{pid}':[/red] {e}")
        return
    # --- autenticação ---
    if pc.ready:
        console.print(f"[green]✓ '{pid}' já está autenticado[/green] [dim](pronto pra usar)[/dim]")
    elif pc.transport in ("codex_oauth", "minimax_oauth"):
        if menu.confirm(f"'{pid}' usa assinatura e ainda NÃO está logado. Fazer login agora?", default=True):
            login(pid)                              # abre o device flow de verdade
        else:
            console.print(f"[yellow]→ logue depois com:[/yellow] okami login {pid}")
    elif pc.transport == "claude_cli":
        ok = "[green]CLI `claude` OK[/green]" if pc.ready else "[yellow]instale e rode `claude login`[/yellow]"
        console.print(f"autenticação: {ok}")
    elif pc.api_key_env:
        s = "[green]chave no .env OK[/green]" if pc.resolved_key() else f"[yellow]falta {pc.api_key_env} no .env[/yellow]"
        console.print(f"autenticação: {s}")
    # --- como usar ---
    console.print(f"\n[bold green]pronto![/bold green] provider [bold]{pid}[/bold] · modelo [bold]{model}[/bold]"
                  + (" · [cyan]DEFAULT[/cyan]" if made_default else ""))
    if made_default:
        console.print("   testar agora: [bold]okami chat \"oi\"[/bold]   ·   trocar modelo: [bold]okami chat -m <id>[/bold]")
    else:
        console.print(f"   usar:  [bold]okami chat -p {pid}[/bold]   ·   tornar default: [bold]okami provider default {pid}[/bold]")
    console.print("[dim]diagnóstico completo: okami doctor[/dim]")


@provider_app.command("list", help=_tr("cli.provider.list", _default="List providers (same as `okami providers`)."))
def provider_list_cmd() -> None:
    """Lista os providers (igual a `okami providers`)."""
    list_providers()


@provider_app.command("remove", help=_tr("cli.provider.remove", _default="Remove a provider from okami.yaml."))
def provider_remove_cmd(provider_id: str = typer.Argument(..., help=_tr("cli.provider.remove.provider_id", _default="ID of the provider to remove."))) -> None:
    """Remove um provider do okami.yaml."""
    import yaml as _yaml
    cfg_path = config_dir() / "okami.yaml"
    raw = (_yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}) or {}
    provs = raw.get("providers") or {}
    if provider_id not in provs:
        console.print(f"[yellow]'{provider_id}' não existe.[/yellow]")
        raise typer.Exit(1)
    del provs[provider_id]
    if raw.get("default_provider") == provider_id:
        raw["default_provider"] = next(iter(provs), None)
        console.print(f"[dim]default reapontado p/ {raw['default_provider']}[/dim]")
    cfg_path.write_text(_yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    console.print(f"[green]✓ removido:[/green] {provider_id}")


@provider_app.command("default", help=_tr("cli.provider.default", _default="Set the default provider (writes an override in okami.local.yaml)."))
def provider_default_cmd(provider_id: str = typer.Argument(..., help=_tr("cli.provider.default.provider_id", _default="ID of the provider to make default."))) -> None:
    """Define o provider default (grava override em okami.local.yaml)."""
    cfg = _load()
    if provider_id not in cfg.providers:
        console.print(f"[red]'{provider_id}' não existe[/red] (okami providers)")
        raise typer.Exit(1)
    _write_local({"default_provider": provider_id})
    console.print(f"[green]✓ default agora é '{provider_id}'[/green]")


@provider_app.command("login", help=_tr("cli.provider.login", _default="Shortcut for `okami login <provider>`."))
def provider_login_cmd(provider_id: str = typer.Argument(..., help=_tr("cli.provider.login.provider_id", _default="Provider to authenticate."))) -> None:
    """Atalho p/ `okami login <provider>`."""
    login(provider_id)


@provider_app.command("models", help=_tr("cli.provider.models", _default="List a provider's models — LIVE via /models, else the catalog."))
def provider_models_cmd(
    provider_id: str = typer.Argument(None, help=_tr("cli.provider.models.provider_id", _default="Provider (empty = all).")),
) -> None:
    """Lista os modelos de um provider — AO VIVO via /models, senão catálogo (estilo `openclaw models list`)."""
    from okami.llm.models import discover_models

    cfg = _load()
    if provider_id and provider_id not in cfg.providers:
        console.print(f"[red]'{provider_id}' não existe[/red] (okami providers)")
        raise typer.Exit(1)
    targets = [provider_id] if provider_id else list(cfg.providers)
    tags = {"live": "[green]ao vivo[/green]", "catalog": "[cyan]catálogo[/cyan]", "none": "[dim]—[/dim]"}
    for pid in targets:
        pc = cfg.providers[pid]
        models, src = discover_models(api_base=pc.api_base, key=pc.resolved_key(),
                                      transport=pc.transport, catalog=pc.models)
        head = f"[bold]{pid}[/bold] {tags[src]}" + (f" [dim]({len(models)})[/dim]" if models else "")
        if provider_id:                            # detalhe: 1 por linha
            console.print(head)
            for m in models:
                mark = "  [cyan]●[/cyan] " if (pc.model or "").endswith(m) else "    "
                console.print(f"{mark}{m}")
            if not models:
                console.print("  [dim]nenhum modelo (endpoint offline ou sem catálogo)[/dim]")
        else:                                      # resumo: 1 linha por provider
            shown = ", ".join(models[:8]) + (f" … (+{len(models) - 8})" if len(models) > 8 else "")
            console.print(f"{head}: {shown or '[dim]—[/dim]'}")


# ============================================================ config (estilo hermes/openclaw) ==
