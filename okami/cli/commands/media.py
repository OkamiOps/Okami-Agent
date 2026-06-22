"""Mídia/extras: say · transcribe · image · acp · tune · paperclip."""
from __future__ import annotations

import json

import typer
from okami.i18n import t as _tr
from rich.table import Table
from pathlib import Path
from okami.cli._app import app, console
from okami.cli._shared import (
    _load, _persona_ws, _resolve_agent,
)


@app.command(help=_tr("cli.transcribe", _default="Transcribe audio with local Whisper (STT)."))
def transcribe(
    audio: str = typer.Argument(..., help=_tr("cli.transcribe.audio", _default="Audio file (m4a/ogg/mp3/wav).")),
    model: str = typer.Option("base", "--model", help=_tr("cli.transcribe.model", _default="Whisper model: tiny|base|small.")),
) -> None:
    """Transcreve um áudio com Whisper local (STT)."""
    from okami.voice.stt import WhisperSTT

    console.print(f"[dim]transcrevendo com whisper '{model}' (baixa o modelo na 1ª vez)…[/dim]")
    console.print(WhisperSTT(model=model).transcribe(audio))


@app.command(help=_tr("cli.say", _default="Generate audio from text (Edge TTS)."))
def say(
    text: str = typer.Argument(..., help=_tr("cli.say.text", _default="Text to speak.")),
    out: str = typer.Option("okami_say.mp3", "--out", "-o", help=_tr("cli.say.out", _default="Output file.")),
    voice: str = typer.Option("pt-BR-AntonioNeural", "--voice", help=_tr("cli.say.voice", _default="Edge TTS voice.")),
) -> None:
    """Gera áudio a partir de texto (Edge TTS)."""
    from okami.voice.tts import EdgeTTS

    EdgeTTS(voice=voice).synthesize(text, out)
    console.print(f"[green]✓ áudio gerado:[/green] {out}")


@app.command(help=_tr("cli.voice", _default="Talk by VOICE (turn-based): speak into the mic, the agent replies by SPEAKING. Ctrl-C exits."))
def voice(
    agent: str = typer.Option(None, "-a", "--agent", help=_tr("cli.voice.agent", _default="Talk by voice as an agent.")),
    workspace: str = typer.Option("workspaces/default", "-w", "--workspace"),
    seconds: float = typer.Option(6.0, "--seconds", help=_tr("cli.voice.seconds", _default="Duration of each mic capture.")),
    whisper: str = typer.Option("base", "--whisper", help=_tr("cli.voice.whisper", _default="Whisper model: tiny|base|small.")),
    tts_voice: str = typer.Option("pt-BR-AntonioNeural", "--tts-voice", help=_tr("cli.voice.tts_voice", _default="Edge TTS voice.")),
    once: bool = typer.Option(False, "--once", help=_tr("cli.voice.once", _default="Single turn (instead of the loop).")),
    yolo: bool = typer.Option(False, "-y", "--yolo", help=_tr("cli.voice.yolo", _default="Auto-approve actions (no click by voice).")),
) -> None:
    """Conversa por VOZ (turn-based): fala no mic → o agente responde FALANDO. Ctrl-C sai.

    Reusa o STT (whisper) + TTS (edge) já existentes via okami.voice.bridge. Precisa das deps de
    voz + um mic/alto-falante na máquina (sounddevice/soundfile + afplay/ffplay)."""
    from okami.channels.terminal import TerminalChannel
    from okami.cli.commands.chat import _wait_for_turn
    from okami.gateway import AgentEndpoint
    from okami.runner import run_task
    from okami.voice.bridge import VoiceBridge, play_file, record_mic
    from okami.voice.stt import WhisperSTT
    from okami.voice.tts import EdgeTTS

    cfg, ws, name, home = _resolve_agent(agent, workspace)
    ws.mkdir(parents=True, exist_ok=True)

    class _CaptureChannel(TerminalChannel):     # captura a fala do agente p/ o TTS (e mostra no terminal)
        def __init__(self):
            super().__init__(name, console=console)
            self.last = ""

        def send(self, chat_id, text: str) -> None:
            self.last = text
            super().send(chat_id, text)

    ch = _CaptureChannel()
    mode = "yolo" if yolo else (cfg.approvals or {}).get("mode", "manual")
    ep = AgentEndpoint(name, cfg, ws, ch, run_task=run_task, approval_mode=mode,
                       agent_home=home, open_fs=True)   # voz = dono: casa isolada + acesso a todo o FS
    cid = "voice"

    def respond(user_text: str) -> str:
        ch.last = ""
        ep.handle(cid, user_text)
        _wait_for_turn(ep, cid)
        return ch.last

    bridge = VoiceBridge(transcribe=WhisperSTT(model=whisper).transcribe, respond=respond,
                         synthesize=EdgeTTS(voice=tts_voice).synthesize,
                         record=lambda: record_mic(seconds), play=play_file)
    console.print(f"[dim]🎙️ voz ({name}) — fala ({seconds}s por turno). Silêncio ou Ctrl-C encerra.[/dim]")
    try:
        if once:
            bridge.turn()
        else:
            bridge.loop(on_turn=lambda u, r, a: u and console.print(f"[bold]você:[/bold] {u}"))
    except KeyboardInterrupt:
        console.print("\n[dim]voz encerrada.[/dim]")


@app.command("paperclip", help=_tr("cli.paperclip", _default="Check the Paperclip connection (injected env + GET /api/agents/me)."))
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


@app.command("acp", help=_tr("cli.acp", _default="ACP (Agent Client Protocol) server — the IDE (Zed/VS Code) drives Okami over stdio. §13."))
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


@app.command("tune", help=_tr("cli.tune", _default="Show the auto-tune (per-model stats + capability recommendation). §7."))
def tune_cmd(agent: str = typer.Option(None, "-a", "--agent"),
            workspace: str = typer.Option(".", "-w", "--workspace")) -> None:
    """Mostra o auto-tune (stats por modelo + recomendação de capability). §7."""
    from okami import learning

    ws = _persona_ws(agent, workspace)
    p = ws / ".okami" / "tuning.json"
    if not p.exists():
        console.print("[dim]sem stats ainda (rode tarefas).[/dim]")
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        console.print(f"[red]tuning.json corrompido:[/red] {e}")   # erro claro, não traceback
        raise typer.Exit(1) from None
    table = Table(title="Auto-tune (§7)")
    for col in ("modelo", "runs", "violations", "loops", "recomendação"):
        table.add_column(col, style="bold" if col == "modelo" else None)
    for model, m in data.items():
        rec = learning.tuned_overrides(ws, model).get("tool_mode", "—")
        table.add_row(model, str(m.get("runs", 0)), str(m.get("violations", 0)),
                      str(m.get("loops", 0)), rec)
    console.print(table)


@app.command("image", help=_tr("cli.image", _default="Generate an image (gpt-image-2 via Codex subscription). With `--ref photo.png` -> transform the reference."))
def image_cmd(
    prompt: str = typer.Argument(..., help=_tr("cli.image.prompt", _default="Description (without --ref) or transform instruction (with --ref).")),
    out: str = typer.Option("image.png", "-o", "--out"),
    ref: list[str] = typer.Option(None, "--ref", help=_tr("cli.image.ref", _default="Reference image(s) (repeat for several).")),
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


@app.command("video", help=_tr("cli.video", _default="Generate a video via the configured provider (media.video). With `--image base.png` for image-to-video; `--list` shows named backends."))
def video_cmd(
    prompt: str = typer.Argument("", help=_tr("cli.video.prompt", _default="What to generate.")),
    out: str = typer.Option("video.mp4", "-o", "--out"),
    image: str = typer.Option("", "--image", help=_tr("cli.video.image", _default="Base image for image-to-video.")),
    list_backends: bool = typer.Option(False, "--list", help=_tr("cli.video.list", _default="List named backends (veo3/kling/pixverse) and their capabilities.")),
) -> None:
    """Gera um vídeo via o provider configurado (media.video). Sem config → mensagem clara, nunca crasha."""
    from okami.cli._shared import _load
    from okami.llm.videogen import generate_video, video_backends
    if list_backends:
        from rich.table import Table
        tbl = Table(title="backends de vídeo (media.video.backend)", title_style="bold")
        for col in ("backend", "model", "áudio", "duração", "aspect"):
            tbl.add_column(col)
        for b in video_backends():
            c = b["capabilities"]
            tbl.add_row(b["name"], b["model"], "sim" if c.get("audio") else "não",
                        f"{c.get('max_duration_s', '?')}s", " ".join(c.get("aspect_ratios", [])))
        console.print(tbl)
        console.print("[dim]use: media.video.backend: <nome> + api_key_env. Ou media.video.url p/ um endpoint próprio.[/dim]")
        return
    if not prompt.strip():
        console.print("[yellow]informe o prompt[/yellow] [dim](ou `okami video --list`).[/dim]")
        raise typer.Exit(2)
    try:
        cfg = _load()
    except Exception:  # noqa: BLE001
        cfg = None
    try:
        path = generate_video(cfg, prompt, out, image=image or None)
    except RuntimeError as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(1) from e
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]falhou:[/red] {e}")
        raise typer.Exit(1) from e
    console.print(f"[green]✓ vídeo:[/green] {path}")


