"""Mídia/extras: say · transcribe · image · acp · tune · paperclip."""
from __future__ import annotations

import json

import typer
from rich.table import Table
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _persona_ws,
)


@app.command()
def transcribe(
    audio: str = typer.Argument(..., help="Arquivo de áudio (m4a/ogg/mp3/wav)."),
    model: str = typer.Option("base", "--model", help="Modelo whisper: tiny|base|small."),
) -> None:
    """Transcreve um áudio com Whisper local (STT)."""
    from okami.voice.stt import WhisperSTT

    console.print(f"[dim]transcrevendo com whisper '{model}' (baixa o modelo na 1ª vez)…[/dim]")
    console.print(WhisperSTT(model=model).transcribe(audio))


@app.command()
def say(
    text: str = typer.Argument(..., help="Texto a falar."),
    out: str = typer.Option("okami_say.mp3", "--out", "-o", help="Arquivo de saída."),
    voice: str = typer.Option("pt-BR-AntonioNeural", "--voice", help="Voz Edge TTS."),
) -> None:
    """Gera áudio a partir de texto (Edge TTS)."""
    from okami.voice.tts import EdgeTTS

    EdgeTTS(voice=voice).synthesize(text, out)
    console.print(f"[green]✓ áudio gerado:[/green] {out}")


@app.command("paperclip")
def paperclip_cmd() -> None:
    """Checa a conexão com o Paperclip (env injetadas + GET /api/agents/me)."""
    import os

    from okami.channels.paperclip import PaperclipClient, PaperclipError

    miss = [k for k in ("PAPERCLIP_API_URL", "PAPERCLIP_API_KEY") if not os.getenv(k)]
    if miss:
        console.print(f"[yellow]faltam env:[/yellow] {', '.join(miss)} "
                      "(o Paperclip injeta isso ao acordar o agente no heartbeat).")
        raise typer.Exit(1)
    try:
        me = PaperclipClient.from_env().me()
    except PaperclipError as e:
        console.print(f"[red]falhou:[/red] {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓ conectado:[/green] agente={me.get('id')} · empresa="
                  f"{me.get('companyId') or (me.get('company') or {}).get('id')} · papel={me.get('role')} "
                  f"· budget={me.get('budget')}")


@app.command("acp")
def acp_cmd(agent: str = typer.Option(None, "-a", "--agent"),
            workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Servidor ACP (Agent Client Protocol) — a IDE (Zed/VS Code) dirige o Okami via stdio. §13."""
    from okami.integrations.acp import run_acp
    from okami.runner import run_task

    if agent:
        from okami.agents import effective_config, load_agents
        from okami.config import load_raw
        spec = load_agents().get(agent)
        graw, _ = load_raw()
        cfg, ws = (effective_config(graw, spec), spec.dir) if spec else (_load(), Path(workspace))
    else:
        cfg, ws = _load(), Path(workspace)
    run_acp(cfg, ws, run_task)


@app.command("tune")
def tune_cmd(agent: str = typer.Option(None, "-a", "--agent"),
            workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Mostra o auto-tune (stats por modelo + recomendação de capability). §7."""
    from okami import learning

    ws = _persona_ws(agent, workspace)
    p = ws / ".okami" / "tuning.json"
    if not p.exists():
        console.print("[dim]sem stats ainda (rode tarefas).[/dim]")
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    table = Table(title="Auto-tune (§7)")
    for col in ("modelo", "runs", "violations", "loops", "recomendação"):
        table.add_column(col, style="bold" if col == "modelo" else None)
    for model, m in data.items():
        rec = learning.tuned_overrides(ws, model).get("tool_mode", "—")
        table.add_row(model, str(m.get("runs", 0)), str(m.get("violations", 0)),
                      str(m.get("loops", 0)), rec)
    console.print(table)


@app.command("image")
def image_cmd(
    prompt: str = typer.Argument(..., help="Descrição (sem --ref) ou instrução de transformação (com --ref)."),
    out: str = typer.Option("image.png", "-o", "--out"),
    ref: list[str] = typer.Option(None, "--ref", help="Imagem(ns) de referência (repita p/ várias)."),
    model: str = typer.Option("gpt-image-2", "--model"),
    size: str = typer.Option("1024x1024", "--size"),
) -> None:
    """Gera imagem (gpt-image-2 via assinatura Codex). Com `--ref foto.png` → transforma a referência."""
    from okami.llm.imagegen import generate_image

    try:
        path = generate_image(prompt, out, references=list(ref) if ref else None, model=model, size=size)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]falhou:[/red] {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓ imagem:[/green] {path}")


