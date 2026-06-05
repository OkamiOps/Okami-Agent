"""Voice bridge — loop de voz turn-based: mic → STT → agente → TTS → alto-falante.

A LÓGICA (transcrever → responder → sintetizar → tocar) é INJETÁVEL e testável; o I/O de hardware
(capturar do mic, tocar no alto-falante) é um adaptador fino de plataforma que roda na máquina do
usuário. Realtime/streaming/barge-in é o passo além (infra de áudio dedicada) — aqui é o turn-based
sólido: você fala, o agente responde falando.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


def _voice_dir() -> Path:
    """Workdir do áudio na CASA (~/.okami/voice), não espalhado como .okami no CWD."""
    from okami.home import okami_home
    return okami_home() / "voice"


@dataclass
class VoiceBridge:
    transcribe: Callable[[Path], str]            # áudio → texto (STT)
    respond: Callable[[str], str]                # texto do usuário → resposta do agente
    synthesize: Callable[[str, Path], Path]      # texto → arquivo de áudio (TTS)
    record: Optional[Callable[[], Path]] = None  # mic → arquivo (hardware; None = sem captura)
    play: Optional[Callable[[Path], None]] = None  # arquivo → alto-falante (hardware)
    workdir: Path = field(default_factory=lambda: _voice_dir())

    def handle_audio(self, audio_in) -> tuple[str, str, Path | None]:
        """Um turno a partir de um ARQUIVO de áudio: transcreve, responde, sintetiza (e toca se houver player).
        Devolve (texto_usuário, texto_resposta, caminho_áudio_resposta). Silêncio → ("", "", None)."""
        user = (self.transcribe(Path(audio_in)) or "").strip()
        if not user:
            return "", "", None
        reply = (self.respond(user) or "").strip()
        out: Path | None = None
        if reply:
            self.workdir.mkdir(parents=True, exist_ok=True)
            out = Path(self.synthesize(reply, self.workdir / "reply.mp3"))
            if self.play is not None:
                self.play(out)
        return user, reply, out

    def turn(self) -> tuple[str, str, Path | None]:
        """Um turno completo capturando do mic (precisa de `record`)."""
        if self.record is None:
            raise RuntimeError("voice bridge sem captura de mic (`record`) — rode num ambiente com áudio")
        return self.handle_audio(self.record())

    def loop(self, *, until: Callable[[], bool] | None = None,
             on_turn: Callable[[str, str, Path | None], None] | None = None) -> None:
        """Loop de conversa por voz (turn-based). Para quando `until()` ou no primeiro silêncio."""
        stop = until or (lambda: False)
        while not stop():
            user, reply, audio = self.turn()
            if on_turn is not None:
                on_turn(user, reply, audio)
            if not user:                            # silêncio = encerra
                break


# ----------------------- adaptadores de HARDWARE (best-effort, máquina do usuário) -----------------
def record_mic(seconds: float = 6.0, samplerate: int = 16000, out: Path | None = None) -> Path:
    """Captura `seconds` do microfone para um WAV (precisa de sounddevice + soundfile)."""
    import sounddevice as sd
    import soundfile as sf
    dst = Path(out or (_voice_dir() / "in.wav"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    audio = sd.rec(int(seconds * samplerate), samplerate=samplerate, channels=1)
    sd.wait()
    sf.write(str(dst), audio, samplerate)
    return dst


def play_file(path) -> None:
    """Toca um arquivo de áudio com o player disponível (afplay/ffplay/mpv/play) — best-effort."""
    import shutil
    import subprocess
    p = str(path)
    for player in ("afplay", "ffplay", "mpv", "play"):
        if shutil.which(player):
            args = ([player, "-nodisp", "-autoexit", p] if player == "ffplay" else [player, p])
            subprocess.run(args, capture_output=True)
            return
    from okami.log import warn
    warn("nenhum player de áudio (afplay/ffplay/mpv) encontrado — playback pulado")
