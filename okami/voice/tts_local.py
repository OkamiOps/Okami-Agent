"""TTS local — roda 100% offline, sem mandar a voz pra nuvem.

Piper (rápido, leve, vozes neurais ONNX) e, opcional, NeuTTS (clone de voz a partir
de um áudio de referência). Mesmo contrato duck-typed do tts.py: classe com
synthesize(self, text, out_path) -> Path. Deps são opcionais e importadas só na hora
de sintetizar, com dica clara de instalação se faltarem.

Saída em WAV (Piper gera PCM nativamente). Nada sai da máquina.
"""

from __future__ import annotations

from pathlib import Path


class PiperTTS:
    """Piper TTS local. `model` é o nome/caminho da voz ONNX (ex.: "pt_BR-faber-medium").

    O modelo é baixado/carregado só quando você sintetiza pela primeira vez — construir
    a instância não toca a rede nem o disco.
    """

    def __init__(self, model: str | None = None, voice: str | None = None, **kw):
        # `model` e `voice` são aliases: o usuário pode chamar de um jeito ou de outro.
        self.model = model or voice
        self.voice = voice or model
        self._extra = kw
        self._loaded = None  # PiperVoice carregada preguiçosamente.

    def _load(self):
        if self._loaded is not None:
            return self._loaded
        try:
            from piper import PiperVoice  # import preguiçoso: dep opcional.
        except ImportError as e:  # pragma: no cover - caminho de erro coberto via monkeypatch
            raise RuntimeError(
                "TTS local 'piper' indisponível. Instale com: pip install piper-tts"
            ) from e
        if not self.model:
            raise RuntimeError(
                "PiperTTS precisa de um modelo de voz (ex.: model='pt_BR-faber-medium')."
            )
        self._loaded = PiperVoice.load(self.model)
        return self._loaded

    def synthesize(self, text: str, out_path) -> Path:
        import wave

        voice = self._load()
        out = Path(out_path)
        with wave.open(str(out), "wb") as wav:
            # API do piper: synthesize_wav escreve PCM no handle aberto.
            voice.synthesize_wav(text, wav)
        return out


class NeuTTS:
    """NeuTTS — clone de voz a partir de um áudio de referência (`ref_audio`).

    Roda local. Dep opcional: importada só na hora de sintetizar. Mesmo contrato
    duck-typed das demais (synthesize(text, out_path) -> Path).
    """

    def __init__(self, ref_audio: str | None = None, model: str | None = None, **kw):
        self.ref_audio = ref_audio
        self.model = model
        self._extra = kw
        self._engine = None

    def _load(self):
        if self._engine is not None:
            return self._engine
        try:
            from neuttsair.neutts import NeuTTSAir  # import preguiçoso: dep opcional.
        except ImportError as e:  # pragma: no cover - caminho de erro coberto via monkeypatch
            raise RuntimeError(
                "TTS local 'neutts' indisponível. Instale com: pip install neuttsair "
                "(veja https://github.com/neuphonic/neutts-air)"
            ) from e
        self._engine = NeuTTSAir(backbone_repo=self.model) if self.model else NeuTTSAir()
        return self._engine

    def synthesize(self, text: str, out_path) -> Path:
        import soundfile as sf  # dep opcional p/ gravar o WAV.

        engine = self._load()
        if not self.ref_audio:
            raise RuntimeError("NeuTTS precisa de ref_audio (áudio de referência p/ o clone).")
        ref = engine.encode_reference(self.ref_audio)
        wav = engine.infer(text, ref)
        out = Path(out_path)
        sf.write(str(out), wav, 24000)
        return out
