"""`okami send` — manda mensagem por um canal SEM acionar o LLM (estilo Hermes `hermes send`).

Pra script/cron/CI avisar no Telegram sem gastar token nem subir sessão:
  okami send "backup concluído ✓" --to telegram:838253616 -a minerva
  okami send "deploy ok" -a minerva            # sem --to → usa o chat 'casa' (/sethome)
  echo "relatório..." | okami send - -a minerva
"""
from __future__ import annotations

import sys

import typer
from okami.cli._app import app, console
from okami.i18n import t as _tr


def _home_chat(agent_dir) -> str:
    """Chat 'casa' do agente (/sethome) — mesmo arquivo que o endpoint usa."""
    try:
        return (agent_dir / ".okami" / "home_chat.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@app.command("send", help=_tr("cli.send", _default="Send a message WITHOUT the LLM (scripts/cron): okami send \"msg\" --to telegram:<chat_id>."))
def send(
    message: str = typer.Argument(..., help=_tr("cli.send.msg", _default="The message ('-' reads from stdin).")),
    to: str = typer.Option("", "--to", "-t", help=_tr("cli.send.to", _default="Target: telegram:<chat_id> (or bare chat_id). Default: the agent's home chat (/sethome).")),
    agent: str = typer.Option("okami", "--agent", "-a", help=_tr("cli.send.agent", _default="Agent whose channel/token to use.")),
) -> None:
    """Entrega direta (sem LLM, sem sessão): útil pra cron/CI/monitoração avisarem no chat."""
    from okami.home import agents_dir
    import yaml

    text = sys.stdin.read() if message.strip() == "-" else message
    if not text.strip():
        console.print("[red]mensagem vazia.[/red]")
        raise typer.Exit(2)

    d = agents_dir() / agent
    af = d / "agent.yaml"
    spec = (yaml.safe_load(af.read_text(encoding="utf-8")) if af.exists() else {}) or {}
    tg = ((spec.get("channels") or {}).get("telegram") or {})
    token = tg.get("token")
    if not token:
        console.print(f"[red]agente '{agent}' não tem token de Telegram[/red] (channels.telegram.token). "
                      "Configure com: okami channel")
        raise typer.Exit(1)

    target = to.strip()
    if target.lower().startswith("telegram:"):
        target = target.split(":", 1)[1].strip()
    if not target:
        target = _home_chat(d)
    if not target:
        console.print("[red]sem destino.[/red] Passe [bold]--to telegram:<chat_id>[/bold] ou defina o chat "
                      "'casa' mandando [bold]/sethome[/bold] pro bot no Telegram.")
        raise typer.Exit(2)

    from okami.channels.telegram import TelegramChannel
    TelegramChannel(token).send(target, text)
    console.print(f"[green]✓ enviado[/green] → telegram:{target} ({len(text)} chars, sem LLM)")
