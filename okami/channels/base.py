"""Abstração de canal (§13) — interface única p/ Telegram, Slack, Discord, etc.

O gateway é channel-agnóstico: fala só com `Channel` (poll/send). Adicionar um canal novo =
implementar esta interface. (Estilo OpenClaw: adapters de canal sob um gateway único.)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Inbound:
    channel: str        # "telegram", "slack", ...
    chat_id: str        # id canônico do chat/peer (string)
    text: str = ""
    audio: str | None = None   # caminho do áudio baixado (voz) → STT transcreve
    image: str | None = None   # caminho da imagem baixada (vision §6) → modelo multimodal
    file: str | None = None    # caminho de documento/vídeo baixado → vai pro inbox do workspace
    file_name: str = ""        # nome original do arquivo (p/ salvar legível no inbox)
    msg_id: str = ""           # id único da mensagem no canal → idempotência por turno (#3)


class Channel:
    name: str = "channel"
    supports_media: bool = False   # canal entrega anexo nativo? (liga a convenção MEDIA:<path>)
    supports_edit: bool = False    # canal edita msg já enviada? (liga streaming-by-edit do status)

    def start(self) -> None:
        """Inicialização opcional (handshake, getMe, etc.)."""

    def poll(self) -> list[Inbound]:  # pragma: no cover - interface
        """Uma rodada de leitura de mensagens novas."""
        raise NotImplementedError

    def send(self, chat_id, text: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def send_audio(self, chat_id, audio_path) -> None:
        """Envia áudio (TTS). Default: ignora (canal sem voz)."""

    def send_media(self, chat_id, path, caption: str = "", voice: bool = False,
                   document: bool = False) -> None:
        """Envia um arquivo como anexo nativo. Default: ignora (canal sem mídia)."""

    def send_status(self, chat_id, text: str):
        """Envia uma mensagem de STATUS e devolve o id dela (p/ editar depois). Default: None (sem edição)."""
        return None

    def edit_message(self, chat_id, msg_id, text: str) -> bool:
        """Edita uma mensagem já enviada. Default: no-op (canal sem edição)."""
        return False

    def allowed(self, chat_id) -> bool:
        return True
