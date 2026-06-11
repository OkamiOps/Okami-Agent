"""Comando `okami channel` — conectar um canal (Telegram) sem o wizard inteiro do `okami setup`.

  okami channel add telegram <token> [--allow 123,456 | --allow-all] [--agent okami]
  okami channel list [--agent okami]
  okami channel remove telegram [--agent okami]
"""
from __future__ import annotations

import typer
import yaml
from okami.cli._app import app, console
from okami.cli._shared import _ensure_agent
from okami.i18n import t as _tr

_TYPES = ("telegram",)   # por enquanto o caminho fácil cobre Telegram; Slack/Discord seguem via config


def _agent_spec(agent_id: str):
    from okami.home import agents_dir
    af = agents_dir() / agent_id / "agent.yaml"
    if not af.exists():
        return None, af
    return (yaml.safe_load(af.read_text(encoding="utf-8")) or {}), af


@app.command("channel", help=_tr("cli.channel", _default="Connect a channel the easy way: okami channel add telegram <token> [--allow ids|--allow-all]."))
def channel(
    action: str = typer.Argument(..., help=_tr("cli.channel.action", _default="add | list | remove.")),
    ctype: str = typer.Argument("", help=_tr("cli.channel.type", _default="Channel type (telegram).")),
    token: str = typer.Argument("", help=_tr("cli.channel.token", _default="Bot token (@BotFather), for `add`.")),
    allow: str = typer.Option("", "--allow", help=_tr("cli.channel.allow", _default="Comma-separated chat ids allowed to talk to the bot.")),
    allow_all: bool = typer.Option(False, "--allow-all", help=_tr("cli.channel.allow_all", _default="Allow ANYONE (insecure — testing only).")),
    agent: str = typer.Option("okami", "--agent", "-a", help=_tr("cli.channel.agent", _default="Agent to configure (default: okami).")),
) -> None:
    """Conecta/lista/remove um canal de um agente, escrevendo o agent.yaml — sem o wizard inteiro."""
    act = action.strip().lower()

    if act == "list":
        spec, af = _agent_spec(agent)
        if not spec:
            console.print(f"[dim]agente '{agent}' não existe ainda — crie com:[/dim] okami channel add telegram <token>")
            return
        chans = spec.get("channels") or {}
        if not chans:
            console.print(f"[dim]nenhum canal configurado p/ '{agent}'.[/dim]")
            return
        console.print(f"[bold]canais de {agent}:[/bold]")
        for name, cc in chans.items():
            who = "todos (allow_all)" if cc.get("allow_all") else (
                ", ".join(str(c) for c in cc.get("allow_chats", [])) or "ninguém ainda (deny-by-default)")
            console.print(f"  [cyan]{name}[/cyan] · {who}")
        return

    if ctype.strip().lower() not in _TYPES:
        console.print(f"[red]tipo '{ctype}' não reconhecido.[/red] Tipos: {', '.join(_TYPES)}.")
        raise typer.Exit(2)

    if act == "remove":
        spec, af = _agent_spec(agent)
        if spec and ctype in (spec.get("channels") or {}):
            del spec["channels"][ctype]
            af.write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False) or "{}\n", encoding="utf-8")
            console.print(f"[green]✓ canal {ctype} removido de {agent}.[/green]")
        else:
            console.print(f"[yellow]{agent} não tinha o canal {ctype}.[/yellow]")
        return

    if act == "add":
        if not token.strip():
            console.print("[red]informe o token:[/red] okami channel add telegram <token>")
            raise typer.Exit(2)
        from okami.cli.commands.setup import _parse_chat_ids
        ids = _parse_chat_ids(allow) if allow.strip() else None
        _ensure_agent(agent, telegram_token=token.strip(), telegram_allow=ids, telegram_allow_all=allow_all)
        console.print(f"[green]✓ Telegram conectado ao agente '{agent}'.[/green]")
        if allow_all:
            console.print("[yellow]⚠ allow_all: QUALQUER pessoa pode falar com o bot. Use só p/ teste.[/yellow]")
        elif ids:
            console.print(f"[dim]liberado p/:[/dim] {', '.join(str(c) for c in ids)}")
        else:
            console.print("[yellow]ninguém liberado ainda[/yellow] — o bot fica MUDO até você liberar alguém. "
                          "Opções: [bold]--allow <id>[/bold], [bold]--allow-all[/bold], ou aprove pelo "
                          "[bold]okami pair[/bold] quando alguém tentar falar.")
        console.print("[dim]suba o gateway com:[/dim] okami gateway")
        return

    console.print(f"[red]ação '{action}' não reconhecida[/red] — use: add | list | remove")
    raise typer.Exit(2)
