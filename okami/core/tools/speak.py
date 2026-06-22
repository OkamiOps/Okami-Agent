"""Tool `text_to_speech` (#10) — o agente RESPONDE em voz.

O Okami já OUVE nota de voz (audio_analyze/Whisper) e já tem a convenção `MEDIA:<path>` + `sendVoice`,
mas faltava a tool que FALA de volta. Aqui o modelo sintetiza voz (engine do DONO: edge/minimax/piper,
em voice.tts) e devolve um `MEDIA:` que o gateway entrega como BOLHA DE VOZ (ffmpeg → ogg/opus) ou,
sem ffmpeg, como arquivo de áudio. A voz/engine é escolha do dono — o modelo não a decide.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from okami.core.tools.base import Tool, ToolContext, ToolResult


def _to_voice_ogg(src: Path) -> Path | None:
    """Converte o áudio p/ ogg/opus (bolha de voz do Telegram) via ffmpeg. None se ffmpeg ausente/falhar."""
    if not shutil.which("ffmpeg"):
        return None
    ogg = src.with_suffix(".ogg")
    try:
        subprocess.run(["ffmpeg", "-y", "-i", str(src), "-c:a", "libopus", "-b:a", "48k", str(ogg)],  # noqa: S607
                       capture_output=True, timeout=60, check=True)
        return ogg if ogg.exists() else None
    except (OSError, subprocess.SubprocessError):
        return None


class TextToSpeech(Tool):
    name = "text_to_speech"
    description = ("Sintetiza VOZ a partir de texto e devolve um áudio que o canal entrega como bolha de "
                   "voz (Telegram). Use p/ responder em ÁUDIO quando o dono pedir ou mandar nota de voz. "
                   "A voz/engine é a configurada pelo dono.")
    args_schema = {"text": "o texto a falar (curto)"}
    required = ("text",)

    def check(self) -> str | None:
        """Disponível se edge-tts está presente OU se o lazy-install resolve no run (default). Só sai do
        registro quando o dep falta E o lazy-install foi desligado."""
        try:
            import edge_tts  # noqa: F401
            return None
        except Exception:  # noqa: BLE001
            from okami.core.lazy_deps import _allow_lazy_installs
            if _allow_lazy_installs():                  # vai auto-instalar no run → tool disponível
                return None
            return "TTS indisponível e lazy-install desligado (instale edge-tts ou configure voice.tts)"

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        import time as _t
        import uuid as _uuid
        text = str(args.get("text") or "").strip()
        if not text:
            return ToolResult(False, "text_to_speech exige 'text' não-vazio.")
        vcfg = (getattr(getattr(ctx, "cfg", None), "voice", None) or {}).get("tts") or {}
        if not vcfg.get("enabled"):
            return ToolResult(False, "TTS não habilitado — configure voice.tts.enabled: true no okami.yaml.")
        from okami.voice import make_tts
        try:
            tts = make_tts(vcfg)
        except ValueError as e:                            # backend desconhecido (typo na config) → erro limpo,
            return ToolResult(False, f"TTS mal configurado: {e}")   # não ValueError escapando do run()
        if tts is None:
            return ToolResult(False, "TTS não configurado (voice.tts) — não dá p/ falar.")
        # .resolve(): MEDIA:<path> exige caminho ABSOLUTO (a regex de extract_media não casa relativo) —
        # se workspace vier relativo, o áudio não chegaria no Telegram. uuid: dois TTS no mesmo ms não colidem.
        out_dir = Path(ctx.workspace).resolve() / ".okami" / "tts"
        out_dir.mkdir(parents=True, exist_ok=True)
        raw = out_dir / f"reply_{int(_t.time() * 1000)}_{_uuid.uuid4().hex[:8]}.mp3"
        try:
            tts.synthesize(text[:3000], raw)
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"falha na síntese de voz: {e}")
        voiced = _to_voice_ogg(raw)                       # bolha de voz se der; senão arquivo de áudio
        media = voiced or raw
        directive = "\n[[audio_as_voice]]" if voiced else ""
        return ToolResult(True, f"MEDIA:{media}{directive}", effect=True)
