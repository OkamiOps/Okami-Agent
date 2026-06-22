"""Tool audio_analyze (pesquisa #7 item 1) — transcreve um áudio do workspace para texto via
Whisper LOCAL (faster-whisper, sem API). Áudio do chat/Telegram vira texto que o modelo lê."""
from __future__ import annotations

from okami.core.tools.base import Tool, ToolResult, _safe_path

_MODELS = {"tiny", "base", "small"}  # modelos leves o bastante p/ rodar local sem GPU


class AudioAnalyze(Tool):
    name = "audio_analyze"
    description = ("Transcreve um arquivo de ÁUDIO (.ogg/.m4a/.mp3/.wav) do workspace para TEXTO via "
                   "Whisper LOCAL — sem API, roda na máquina. Use quando chegar uma nota de voz, "
                   "um áudio ou gravação e você precisar do que foi dito. Passe o caminho do arquivo.")
    args_schema = {"path": "caminho do áudio no workspace",
                   "model": "(opc) tiny|base|small (default base — maior = mais preciso, mais lento)",
                   "language": "(opc) idioma (ex.: pt, en) — vazio = detecta sozinho"}
    required = ("path",)

    def check(self):
        """check_fn (item 27): disponível se faster-whisper está presente OU se o lazy-install vai
        resolver no run (default). Só PODA do registro quando o dep falta E o lazy-install foi desligado."""
        import importlib.util
        if importlib.util.find_spec("faster_whisper") is not None:
            return None
        from okami.core.lazy_deps import _allow_lazy_installs
        if _allow_lazy_installs():                      # vai auto-instalar no run → tool disponível
            return None
        return 'pacote de voz não instalado e lazy-install desligado — pip install "okami-agent[voice]"'

    def run(self, args, ctx):
        rel = args.get("path")
        if not isinstance(rel, str) or not rel:
            return ToolResult(False, "audio_analyze: 'path' precisa ser uma string não-vazia.", effect=False)
        try:
            p = _safe_path(ctx, rel)
        except ValueError as e:
            return ToolResult(False, str(e), effect=False)
        if not p.exists():
            return ToolResult(False, f"audio_analyze: arquivo não encontrado: {rel}", effect=False)

        # defaults vêm de ctx.cfg.voice['stt'] se houver (device/compute_type/idioma do dono),
        # mas os args da chamada têm prioridade. cfg.voice é um dict {"stt": {...}, "tts": {...}}.
        stt_cfg = {}
        cfg = getattr(ctx, "cfg", None)
        if cfg is not None:
            voice = getattr(cfg, "voice", None) or {}
            if isinstance(voice, dict):
                stt_cfg = voice.get("stt") or {}

        model = args.get("model") or stt_cfg.get("model") or "base"
        if model not in _MODELS:                       # clamp: modelo inválido cai no default seguro
            model = "base"
        language = args.get("language") or stt_cfg.get("language")
        device = stt_cfg.get("device", "cpu")
        compute_type = stt_cfg.get("compute_type", "int8")

        from okami.voice.stt import WhisperSTT
        try:
            text = WhisperSTT(model=model, device=device,
                              compute_type=compute_type, language=language).transcribe(str(p))
        except Exception as e:  # noqa: BLE001 — decode/modelo indisponível
            return ToolResult(False, f"audio_analyze falhou: {e}", effect=False)

        ctx.read_files.add(rel)
        text = (text or "").strip()
        return ToolResult(True, text or "(silêncio/sem fala)", effect=False)
