"""Cliente Telegram Bot API (urllib, sem dependência extra).

Long polling (getUpdates) + sendMessage. Cada agente usa o seu token (no agent.yaml).
"""

from __future__ import annotations

import json
import secrets
import tempfile
import urllib.request
from pathlib import Path

from okami.channels.base import Channel, Inbound


class TelegramClient:
    def __init__(self, token: str, api_base: str = "https://api.telegram.org"):
        self.api_base = api_base
        self.token = token
        self.base = f"{api_base}/bot{token}"

    def _call(self, method: str, params: dict, timeout: float = 35.0) -> dict:
        data = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(f"{self.base}/{method}", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))

    def get_me(self) -> dict:
        return self._call("getMe", {}).get("result", {})

    def get_updates(self, offset: int = 0, timeout: int = 30) -> list[dict]:
        res = self._call("getUpdates", {"offset": offset, "timeout": timeout}, timeout=timeout + 5)
        return res.get("result", [])

    def send_message(self, chat_id, text: str) -> dict:
        # Telegram corta em 4096; deixamos margem.
        return self._call("sendMessage", {"chat_id": chat_id, "text": text[:4000]})

    def download_file(self, file_id: str) -> str:
        """Baixa um arquivo (voz/áudio) para um temp e devolve o caminho."""
        fp = self._call("getFile", {"file_id": file_id}).get("result", {}).get("file_path")
        if not fp:
            raise RuntimeError("getFile sem file_path")
        url = f"{self.api_base}/file/bot{self.token}/{fp}"
        out = Path(tempfile.gettempdir()) / f"okami_in_{secrets.token_hex(4)}{Path(fp).suffix or '.oga'}"
        with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310
            out.write_bytes(r.read())
        return str(out)

    def send_audio(self, chat_id, audio_path) -> dict:
        """Envia um arquivo de áudio (mp3) via multipart."""
        boundary = "----okami" + secrets.token_hex(12)
        path = Path(audio_path)
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode(),
            (f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{path.name}\"\r\n"
             "Content-Type: audio/mpeg\r\n\r\n").encode(),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        body = b"".join(parts)
        req = urllib.request.Request(f"{self.base}/sendAudio", data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))


class TelegramChannel(Channel):
    """Adapter Telegram para a interface Channel do gateway."""

    name = "telegram"

    def __init__(self, token: str, allow_chats=None, allow_all: bool = False):
        self.client = TelegramClient(token)
        self._offset = 0
        self.allow = {str(c) for c in (allow_chats or [])}
        self.allow_all = bool(allow_all)   # SÓ explícito abre p/ todos (deny-by-default)

    def poll(self) -> list[Inbound]:
        out = []
        for u in self.client.get_updates(offset=self._offset, timeout=30):
            self._offset = u["update_id"] + 1
            msg = u.get("message") or {}
            chat = (msg.get("chat") or {}).get("id")
            if chat is None:
                continue
            voice = msg.get("voice") or msg.get("audio")   # nota de voz ou áudio
            if voice and voice.get("file_id"):
                try:
                    audio = self.client.download_file(voice["file_id"])
                    out.append(Inbound("telegram", str(chat), text="", audio=audio))
                    continue
                except Exception:  # noqa: BLE001 — falhou o download → ignora o áudio
                    pass
            photo = msg.get("photo")                        # foto → vision (§6)
            if photo:
                try:
                    img = self.client.download_file(photo[-1]["file_id"])   # maior resolução
                    out.append(Inbound("telegram", str(chat), text=msg.get("caption", ""), image=img))
                    continue
                except Exception:  # noqa: BLE001
                    pass
            txt = msg.get("text")
            if txt:
                out.append(Inbound("telegram", str(chat), text=txt))
        return out

    def send(self, chat_id, text: str) -> None:
        self.client.send_message(chat_id, text)

    def send_audio(self, chat_id, audio_path) -> None:
        self.client.send_audio(chat_id, audio_path)

    def allowed(self, chat_id) -> bool:
        # DENY-BY-DEFAULT: sem allowlist, NINGUÉM passa (a não ser allow_all explícito). Agente com
        # shell/tools/memória atrás de um bot público é perigoso → fail-closed.
        if self.allow:
            return str(chat_id) in self.allow
        return self.allow_all


class TelegramGroupChannel:
    """Canal de GRUPO (§10): N bots num mesmo chat. Um listener (1 token) lê as mensagens HUMANAS
    (ignora as dos próprios bots → anti-loop) e cada agente envia PELA SUA token. Usado pelo
    GroupEndpoint, que roda o GroupRoom (moderador decide quem fala)."""

    name = "telegram-group"

    def __init__(self, tokens: dict[str, str], listen_token: str | None = None,
                 allow_chats=None, api_base: str = "https://api.telegram.org", allow_all: bool = False):
        self.clients = {aid: TelegramClient(tok, api_base) for aid, tok in tokens.items()}
        self.listener = TelegramClient(listen_token or next(iter(tokens.values())), api_base)
        self._offset = 0
        self.allow = {str(c) for c in (allow_chats or [])}
        self.allow_all = bool(allow_all)   # deny-by-default (só explícito abre)
        self._bot_ids: set[int] = set()

    def start(self) -> None:
        for c in self.clients.values():               # descobre os ids dos próprios bots (p/ filtrar)
            try:
                me = c.get_me()
                if me.get("id"):
                    self._bot_ids.add(me["id"])
            except Exception:  # noqa: BLE001
                pass

    def poll(self) -> list[Inbound]:
        out = []
        for u in self.listener.get_updates(offset=self._offset, timeout=30):
            self._offset = u["update_id"] + 1
            msg = u.get("message") or {}
            frm = msg.get("from") or {}
            if frm.get("is_bot") or frm.get("id") in self._bot_ids:
                continue                               # mensagem de um dos nossos bots → ignora (anti-loop)
            chat = (msg.get("chat") or {}).get("id")
            txt = msg.get("text")
            if chat is not None and txt:
                out.append(Inbound("telegram", str(chat), text=txt))
        return out

    def send_as(self, agent_id, chat_id, text: str) -> None:
        c = self.clients.get(agent_id)
        if c:                                          # cada agente fala com a SUA identidade/token
            c.send_message(chat_id, text)

    def allowed(self, chat_id) -> bool:
        if self.allow:                       # deny-by-default (igual ao TelegramChannel)
            return str(chat_id) in self.allow
        return self.allow_all
