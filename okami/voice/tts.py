"""TTS — síntese de voz. Edge TTS (grátis, ótimas vozes) e MiniMax (token plan do user).

Devolve um arquivo de áudio (mp3). Deps opcionais. MiniMax usa a API T2A (schema a confirmar).
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path


class EdgeTTS:
    voice_compatible = True            # #11: saída opus → vira bolha de voz nativa no Telegram

    def __init__(self, voice: str = "pt-BR-AntonioNeural", rate: str = "+0%"):
        self.voice = voice
        self.rate = rate

    def synthesize(self, text: str, out_path) -> Path:
        import asyncio

        from okami.core.lazy_deps import ensure
        ensure("tts.edge")                             # auto-instala edge-tts na 1ª vez
        import edge_tts

        out = Path(out_path)

        async def _go():
            await edge_tts.Communicate(text, self.voice, rate=self.rate).save(str(out))

        asyncio.run(_go())
        return out

    def stream(self, text: str):
        """#11: streaming opcional — gera chunks de áudio (bytes) conforme o provider entrega, p/ entrega
        de voz de baixa latência (decodifica enquanto fala). Yield de bytes de áudio."""
        import asyncio

        from okami.core.lazy_deps import ensure
        ensure("tts.edge")                             # auto-instala edge-tts na 1ª vez
        import edge_tts

        async def _collect():
            chunks = []
            async for ch in edge_tts.Communicate(text, self.voice, rate=self.rate).stream():
                if ch.get("type") == "audio" and ch.get("data"):
                    chunks.append(ch["data"])
            return chunks

        yield from asyncio.run(_collect())


class MiniMaxTTS:
    """MiniMax T2A (text-to-audio). Usa o token plan do user. Schema a CONFIRMAR nos docs."""

    def __init__(self, api_key: str, base_url: str = "https://api.minimax.io",
                 model: str = "speech-02-hd", voice: str = "male-qn-qingse"):
        self.api_key = api_key
        self.url = base_url.rstrip("/") + "/v1/t2a_v2"
        self.model = model
        self.voice = voice

    def synthesize(self, text: str, out_path) -> Path:
        body = json.dumps({
            "model": self.model,
            "text": text,
            "stream": False,
            "voice_setting": {"voice_id": self.voice, "speed": 1.0},
            "audio_setting": {"format": "mp3"},
        }).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            data = json.loads(r.read().decode("utf-8"))
        # resposta traz o áudio em hex (data.audio) — converte p/ bytes.
        audio_hex = (data.get("data") or {}).get("audio", "")
        if not audio_hex:                            # 200 SEM áudio (glitch/schema) → erro claro, não MP3 0-byte
            raise RuntimeError(f"MiniMax não retornou áudio: {json.dumps(data)[:200]}")
        out = Path(out_path)
        out.write_bytes(bytes.fromhex(audio_hex))
        return out
