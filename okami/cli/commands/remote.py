"""Comando `okami remote` — gerencia a ALLOWLIST de hosts do ambiente remoto (SSH/Tailscale).

  okami remote add <alias> <host> [--ssh] [--cwd /caminho]
  okami remote list
  okami remote remove <alias>

A allowlist é a barreira de segurança no Telegram/canais remotos (só alias listado é alcançável).
No terminal o agente pode conectar a qualquer host, mas configurar aqui dá um atalho (`/remote prod`).
"""
from __future__ import annotations

import typer
import yaml

from okami.cli._app import app, console


@app.command("remote", help="Hosts remotos (SSH/Tailscale): okami remote add <alias> <host> [--ssh] [--cwd P] | list | remove")
def remote(
    action: str = typer.Argument(..., help="add | list | remove"),
    alias: str = typer.Argument("", help="apelido do host (ex.: prod)"),
    host: str = typer.Argument("", help="host: nome Tailscale ou user@maquina (p/ add)"),
    ssh: bool = typer.Option(False, "--ssh", help="usar ssh normal em vez de Tailscale SSH"),
    cwd: str = typer.Option("", "--cwd", help="diretório de trabalho remoto (cd antes de cada comando)"),
) -> None:
    from okami.config import find_config
    from okami.core.safe_io import secure_write_yaml
    try:
        path = find_config()
    except FileNotFoundError:
        console.print("[red]okami.yaml não encontrado[/red] — rode `okami setup` (ou crie um okami.yaml).")
        raise typer.Exit(2)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    hosts = data.setdefault("remote", {}).setdefault("hosts", {})
    act = action.strip().lower()

    if act == "list":
        if not hosts:
            console.print("[dim]nenhum host remoto configurado.[/dim] Adicione com: "
                          "okami remote add <alias> <host>")
            return
        console.print("[bold]hosts remotos:[/bold]")
        for a, spec in hosts.items():
            extra = f", cwd {spec['cwd']}" if isinstance(spec, dict) and spec.get("cwd") else ""
            via = spec.get("via", "tailscale") if isinstance(spec, dict) else "tailscale"
            h = spec.get("host", "?") if isinstance(spec, dict) else spec
            console.print(f"  [cyan]{a}[/cyan] · {h} (via {via}{extra})")
        return

    if act == "add":
        if not alias.strip() or not host.strip():
            console.print("[red]uso:[/red] okami remote add <alias> <host> [--ssh] [--cwd /caminho]")
            raise typer.Exit(2)
        spec: dict = {"host": host.strip(), "via": "ssh" if ssh else "tailscale"}
        if cwd.strip():
            spec["cwd"] = cwd.strip()
        hosts[alias.strip()] = spec
        secure_write_yaml(path, data)              # atômico + backup (.bak/.last-good)
        console.print(f"[green]✓ host '{alias}' → {host} (via {spec['via']}) adicionado.[/green]")
        console.print(f"[dim]o agente conecta com:[/dim] /remote {alias}  (ou a tool remote_connect)")
        return

    if act == "remove":
        if alias.strip() in hosts:
            del hosts[alias.strip()]
            secure_write_yaml(path, data)
            console.print(f"[green]✓ host '{alias}' removido.[/green]")
        else:
            console.print(f"[yellow]'{alias}' não estava configurado.[/yellow]")
        return

    console.print(f"[red]ação '{action}' não reconhecida[/red] — use: add | list | remove")
    raise typer.Exit(2)
