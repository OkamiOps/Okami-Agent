"""Comando `okami fs` — liberar acesso a arquivos numa linha (padrão de mercado: OpenClaw workspaceOnly).

  okami fs home        → o agente alcança TUDO embaixo de ~/ (Documents, Pictures, Desktop, Downloads…)
  okami fs full        → filesystem inteiro
  okami fs workspace   → volta ao jail (default seguro — deny-by-default p/ Telegram)
  okami fs home --allow /Volumes/x,/data   → home + pastas extras fora dela

Escreve `tools.fs` (+ allow_paths) no agent.yaml. Segredo (.env/.ssh/.aws) segue bloqueado nos 3 modos."""
from __future__ import annotations

import typer
import yaml
from okami.cli._app import app, console
from okami.i18n import t as _tr

_MODES = ("workspace", "home", "full")


@app.command("fs", help=_tr("cli.fs", _default="File access in one line: okami fs home|full|workspace [--allow extra,dirs]."))
def fs(
    mode: str = typer.Argument(..., help=_tr("cli.fs.mode", _default="workspace (jail) | home (ANY folder under ~/: Videos, Music, anything) | full (ANY folder on the machine).")),
    allow: str = typer.Option("", "--allow", help=_tr("cli.fs.allow", _default="Comma-separated EXTRA dirs beyond the profile (e.g. /Volumes/x).")),
    agent: str = typer.Option("okami", "--agent", "-a", help=_tr("cli.fs.agent", _default="Agent to configure (default: okami).")),
) -> None:
    """Define o perfil de acesso a arquivos do agente — sem editar YAML na mão."""
    m = mode.strip().lower()
    if m not in _MODES:
        console.print(f"[red]modo '{mode}' inválido.[/red] Use: [bold]workspace[/bold] (jail) · "
                      "[bold]home[/bold] (tudo em ~/) · [bold]full[/bold] (FS inteiro).")
        raise typer.Exit(2)
    from okami.home import agents_dir
    d = agents_dir() / agent
    af = d / "agent.yaml"
    spec = (yaml.safe_load(af.read_text(encoding="utf-8")) if af.exists() else {}) or {}
    tools = spec.setdefault("tools", {})
    tools["fs"] = m
    tools.pop("open_fs", None)                         # `fs` é o knob canônico → tira o alias antigo
    extra = [s.strip() for s in allow.replace(";", ",").split(",") if s.strip()]
    if extra:
        tools["allow_paths"] = extra
    elif m == "workspace":
        tools.pop("allow_paths", None)                 # voltar ao jail limpa os extras
    d.mkdir(parents=True, exist_ok=True)
    af.write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False) or "{}\n", encoding="utf-8")

    if m == "home":
        console.print(f"[green]✓ {agent}: liberado QUALQUER pasta embaixo de ~/[/green] — Vídeos, Música, "
                      "Documentos, Imagens, Downloads, Desktop e [bold]qualquer outra[/bold] que você tenha lá. "
                      "Sem whitelist: é a sua pasta pessoal inteira.")
        console.print("[dim]pasta fora de ~/ (disco externo, /data…)? use [/dim]okami fs full[dim] ou [/dim]"
                      "okami fs home --allow /Volumes/Externo")
    elif m == "full":
        console.print(f"[green]✓ {agent}: liberado o FILESYSTEM INTEIRO[/green] — qualquer pasta da máquina "
                      "(home, /Volumes, discos externos, /data, o que for). "
                      "[yellow]Use só em máquina de confiança.[/yellow]")
    else:
        console.print(f"[green]✓ {agent}: confinado ao workspace (jail seguro).[/green] "
                      "[dim]Pra abrir tudo: [/dim]okami fs home[dim] (sua home) ou [/dim]okami fs full[dim] (a máquina toda).[/dim]")
    if extra:
        console.print(f"[dim]+ extras:[/dim] {', '.join(extra)}")
    console.print("[dim]segredos (.env/.ssh/.aws) seguem bloqueados. Reinicie o gateway p/ aplicar:[/dim] okami gateway")
