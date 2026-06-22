"""STT — transcrição de áudio com faster-whisper (LOCAL, nativo, sem API).

Recebe um arquivo de áudio (ogg/m4a/mp3/wav — decodifica via PyAV) e devolve o texto.
Modelo carregado sob demanda e cacheado. Dep opcional: `pip install "okami-agent[voice]"`.
"""

from __future__ import annotations


class WhisperSTT:
    def __init__(self, model: str = "base", device: str = "cpu",
                 compute_type: str = "int8", language: str | None = None):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None

    def _load(self):
        if self._model is None:
            from okami.core.lazy_deps import ensure
            ensure("stt.whisper")                      # auto-instala faster-whisper na 1ª vez (sem o usuário fazer pip)
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio_path) -> str:
        segments, _info = self._load().transcribe(str(audio_path), language=self.language, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
