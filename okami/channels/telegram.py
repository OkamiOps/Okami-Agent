"""Cliente Telegram Bot API (urllib, sem dependência extra).

Long polling (getUpdates) + sendMessage. Cada agente usa o seu token (no agent.yaml).
"""

from __future__ import annotations

import json
import secrets
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from okami.channels import media as _media
from okami.channels.base import Channel, Inbound

_PHOTO_MAX = 10 * 1024 * 1024      # sendPhoto recusa >10MB → cai para sendDocument
_UPLOAD_MAX = 50 * 1024 * 1024     # upload do Bot API público capa em 50MB
_DOWNLOAD_MAX = 20 * 1024 * 1024   # getFile capa em 20MB (entrada)


def _file_size(path) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def _split_message(text: str, limit: int = 4000) -> list[str]:
    """Quebra em pedaços ≤limit preferindo fronteira (parágrafo>linha>frase>espaço>corte duro).
    Telegram corta em 4096 — ANTES a gente TRUNCAVA (perdia o resto); agora manda tudo, em partes."""
    text = text or ""
    if len(text) <= limit:
        return [text]
    out, rest = [], text
    while len(rest) > limit:
        window = rest[:limit]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "), window.rfind(" "))
        if cut <= 0:
            cut = limit                       # sem fronteira → corte duro
        out.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        out.append(rest)
    parts = _balance_fences(out)
    if len(parts) > 1:                        # indicador (i/N) em msg longa partida (paridade Hermes)
        n = len(parts)
        parts = [f"{p}\n\n({i}/{n})" for i, p in enumerate(parts, 1)]
    return parts


def _last_fence_lang(part: str) -> str:
    """Linguagem do ÚLTIMO ``` da parte (abertura → 'python'; fechamento → '')."""
    lang = ""
    for line in part.splitlines():
        s = line.lstrip()
        if s.startswith("```"):
            lang = s[3:].strip()
    return lang


def _balance_fences(parts: list[str]) -> list[str]:
    """#9: bloco de código que atravessa o corte → fecha o ``` na parte atual e REABRE na próxima
    (com a linguagem), pra cada parte renderizar como markdown válido. Sem fence, não muda nada."""
    out: list[str] = []
    carry: str | None = None                  # linguagem do fence que ficou aberto da parte anterior
    for part in parts:
        if carry is not None:
            part = f"```{carry}\n{part}"        # reabre o bloco aberto antes
        if part.count("```") % 2 == 1:         # fence ainda aberta ao fim desta parte
            carry = _last_fence_lang(part)
            part = part.rstrip() + "\n```"      # fecha aqui
        else:
            carry = None
        out.append(part)
    return out


def _is_connect_error(e: Exception) -> bool:
    """True se o erro significa que a conexão NUNCA foi estabelecida (recusada/DNS) — então retransmitir
    é seguro mesmo em método não-idempotente. Read-timeout/OSError genérico NÃO contam (ambíguos)."""
    import socket
    reason = getattr(e, "reason", e)
    return isinstance(reason, (ConnectionRefusedError, socket.gaierror))


class TelegramClient:
    def __init__(self, token: str, api_base: str = "https://api.telegram.org"):
        self.api_base = api_base
        self.token = token
        self.base = f"{api_base}/bot{token}"

    def _call(self, method: str, params: dict, timeout: float = 35.0, *, _sleep=time.sleep) -> dict:
        """POST com RETRY/BACKOFF: 429 respeita retry_after; 5xx/rede instável → backoff; 4xx → erro.

        Dedupe (bug #9): em método NÃO-idempotente (sendMessage/edit/…), NÃO retransmite num erro de
        rede AMBÍGUO (read-timeout, OSError genérico) — o Telegram pode JÁ ter recebido → retransmitir
        duplicaria a mensagem. Só retransmite quando a conexão claramente NÃO foi estabelecida
        (recusada/DNS). Métodos `get*` são idempotentes → retransmitem livremente."""
        data = json.dumps(params).encode("utf-8")
        idempotent = method.startswith("get")
        last: Exception | None = None
        for attempt in range(1, 4):
            req = urllib.request.Request(f"{self.base}/{method}", data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 429:                         # flood control → espera o que o Telegram pedir
                    try:
                        wait = float(json.loads(e.read()).get("parameters", {}).get("retry_after", 1))
                    except Exception:  # noqa: BLE001
                        wait = 1.0
                elif 500 <= e.code < 600:
                    wait = min(8.0, 2 ** attempt)
                else:
                    raise                                  # 4xx (não-429) = erro real, não insiste
                if attempt < 3:
                    _sleep(wait)
            except (urllib.error.URLError, TimeoutError, OSError) as e:   # rede instável
                last = e
                if not idempotent and not _is_connect_error(e):   # ambíguo num send → não retransmite (anti-dupe)
                    raise
                if attempt < 3:
                    _sleep(min(8.0, 2 ** attempt))
        if last:
            raise last
        return {}

    def get_me(self) -> dict:
        return self._call("getMe", {}).get("result", {})

    def get_updates(self, offset: int = 0, timeout: int = 30) -> list[dict]:
        res = self._call("getUpdates", {"offset": offset, "timeout": timeout}, timeout=timeout + 5)
        return res.get("result", [])

    def send_message(self, chat_id, text: str, thread: int | None = None) -> dict:
        from okami.channels.markdown_telegram import to_html, to_plain
        res: dict = {}
        for chunk in _split_message(text, 4000):          # >4096 → várias partes (não trunca mais)
            p = {"chat_id": chat_id, "text": chunk}
            if thread is not None:
                p["message_thread_id"] = thread           # tópico de fórum (conversa paralela)
            # FORMATAÇÃO (Hermes): markdown do agente (e HTML cru que ele às vezes manda) vira HTML do
            # Telegram (negrito/código/link de verdade). Se a API recusar o parse (entidade quebrada/tag
            # partida no split), cai p/ TEXTO PURO LIMPO (to_plain) — NUNCA cru com ** e tags visíveis.
            rendered = to_html(chunk)
            if rendered != chunk:
                try:
                    res = self._call("sendMessage", dict(p, text=rendered, parse_mode="HTML"))
                    continue
                except urllib.error.HTTPError:
                    p["text"] = to_plain(chunk)            # parse recusado → plain legível (sem markup)
            res = self._call("sendMessage", p)
        return res

    def edit_message(self, chat_id, message_id, text: str, thread: int | None = None) -> bool:
        """Edita uma mensagem (editMessageText) — base do streaming-by-edit. HTML com fallback p/ cru;
        ignora o 'message is not modified' (texto igual) e erros best-effort (edição nunca quebra o turno)."""
        from okami.channels.markdown_telegram import to_html, to_plain
        p = {"chat_id": chat_id, "message_id": int(message_id), "text": text[:4000]}
        if thread is not None:
            p["message_thread_id"] = thread
        rendered = to_html(p["text"])
        try:
            if rendered != p["text"]:
                try:
                    self._call("editMessageText", dict(p, text=rendered, parse_mode="HTML"))
                    return True
                except urllib.error.HTTPError:
                    p["text"] = to_plain(p["text"])        # parse recusado → plain legível (não cru)
            self._call("editMessageText", p)
            return True
        except Exception:  # noqa: BLE001 — "not modified"/rede → best-effort
            return False

    def send_chat_action(self, chat_id, action: str = "typing", thread: int | None = None) -> None:
        try:
            p = {"chat_id": chat_id, "action": action}
            if thread is not None:
                p["message_thread_id"] = thread
            self._call("sendChatAction", p)
        except Exception:  # noqa: BLE001 — typing é best-effort
            pass

    def send_approval(self, chat_id, text: str, nonce: str = "", thread: int | None = None) -> dict:
        """Aprovação com BOTÕES inline (✅/❌). `nonce` (P1.3) amarra o clique a ESTE pedido — clique
        velho/deslocado de outra ação não aprova (anti-stale). Sem nonce mantém o formato antigo."""
        from okami.channels.markdown_telegram import to_html, to_plain
        sfx = f"{nonce}:" if nonce else ""
        kb = {"inline_keyboard": [[{"text": "✅ Aprovar", "callback_data": f"okapprove:{sfx}yes"},
                                   {"text": "❌ Negar", "callback_data": f"okapprove:{sfx}no"}]]}
        p = {"chat_id": chat_id, "text": text, "reply_markup": kb}
        if thread is not None:
            p["message_thread_id"] = thread
        rendered = to_html(text)                            # FORMATA a aprovação (era CRUA: ** e [tool] visíveis)
        if rendered != text:
            try:
                return self._call("sendMessage", dict(p, text=rendered, parse_mode="HTML"))
            except urllib.error.HTTPError:
                p["text"] = to_plain(text)                  # parse recusado → plain legível (botões preservados)
        return self._call("sendMessage", p)

    def set_my_commands(self, commands: list[dict]) -> None:
        """Registra o menu do botão '/' (setMyCommands). Best-effort — menu é cosmético."""
        try:
            self._call("setMyCommands", {"commands": commands})
        except Exception:  # noqa: BLE001
            pass

    def set_reaction(self, chat_id, message_id, emoji: str) -> None:
        """Reage à mensagem (setMessageReaction). Best-effort — o set de emojis do Telegram é limitado;
        emoji inválido só não aparece (não quebra o turno)."""
        try:
            self._call("setMessageReaction", {"chat_id": chat_id, "message_id": int(message_id),
                                              "reaction": [{"type": "emoji", "emoji": emoji}]})
        except Exception:  # noqa: BLE001
            pass

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
        except Exception:  # noqa: BLE001
            pass

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

    def _call_multipart(self, method: str, params: dict, field: str, path,
                        timeout: float = 120.0) -> dict:
        """POST multipart/form-data com UM arquivo (`field`) + campos extras (`params`)."""
        import mimetypes
        p = Path(path)
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        boundary = "----okami" + secrets.token_hex(12)
        parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
                 for k, v in params.items()]
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
                      f"filename=\"{p.name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode())
        parts.append(p.read_bytes())
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        req = urllib.request.Request(f"{self.base}/{method}", data=b"".join(parts), method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8"))

    def send_audio(self, chat_id, audio_path) -> dict:
        """Envia um arquivo de áudio (mp3/m4a) via multipart (mantido p/ o TTS do gateway)."""
        return self._call_multipart("sendAudio", {"chat_id": chat_id}, "audio", audio_path)

    def send_media(self, chat_id, path, caption: str = "", thread: int | None = None,
                   voice: bool = False, document: bool = False) -> dict:
        """Roteia um arquivo pro método nativo certo (estilo Hermes): foto/animação/vídeo/voz/
        áudio/documento pela EXTENSÃO. `document=True` força documento (imagem sem recompressão);
        `voice=True` manda .ogg/.opus como bolha de voz. Foto grande/recusada → documento."""
        ext = Path(str(path)).suffix.lower().lstrip(".")
        size = _file_size(path)
        if size > _UPLOAD_MAX:
            raise ValueError(f"arquivo de {size // (1024 * 1024)}MB excede os 50MB do Bot API")
        if document:
            method, field = "sendDocument", "document"
        elif ext in _media.IMAGE_EXTS:
            if size > _PHOTO_MAX:                          # sendPhoto capa em 10MB
                method, field = "sendDocument", "document"
            else:
                method, field = "sendPhoto", "photo"
        elif ext in _media.ANIMATION_EXTS:
            method, field = "sendAnimation", "animation"
        elif ext in _media.VIDEO_EXTS:
            method, field = "sendVideo", "video"
        elif voice and ext in _media.VOICE_EXTS:
            method, field = "sendVoice", "voice"
        elif ext in {"mp3", "m4a"}:                        # sendAudio só aceita mp3/m4a
            method, field = "sendAudio", "audio"
        else:
            method, field = "sendDocument", "document"
        params: dict = {"chat_id": chat_id}
        if caption:
            params["caption"] = caption[:1024]             # limite de caption do Telegram
        if thread is not None:
            params["message_thread_id"] = thread
        try:
            return self._call_multipart(method, params, field, path)
        except urllib.error.HTTPError:
            if method == "sendPhoto":                      # foto recusada (formato/dimensão) → documento
                return self._call_multipart("sendDocument", params, "document", path)
            raise


class TelegramChannel(Channel):
    """Adapter Telegram para a interface Channel do gateway."""

    name = "telegram"
    supports_media = True      # liga a convenção MEDIA:<path> no prompt do gateway
    supports_edit = True       # liga o streaming-by-edit (status editado ao vivo)

    def __init__(self, token: str, allow_chats=None, allow_all: bool = False):
        self.client = TelegramClient(token)
        self._offset = 0
        self.allow = {str(c) for c in (allow_chats or [])}
        self.allow_all = bool(allow_all)   # SÓ explícito abre p/ todos (deny-by-default)

    @staticmethod
    def _decode(chat_id) -> tuple[str, int | None]:
        """'chat:thread' → (chat, thread). Tópicos do Telegram viram sessões separadas no endpoint."""
        s = str(chat_id)
        if ":" in s:
            real, _, t = s.rpartition(":")
            if t.lstrip("-").isdigit():
                return real, int(t)
        return s, None

    def poll(self) -> list[Inbound]:
        out = []
        for u in self.client.get_updates(offset=self._offset, timeout=30):
            self._offset = u["update_id"] + 1
            cq = u.get("callback_query")                   # clique num botão inline (aprovação)
            if cq:
                self.client.answer_callback(cq.get("id", ""))   # tira o "spinner" do botão
                data = cq.get("data") or ""
                cmsg = cq.get("message") or {}
                chat = (cmsg.get("chat") or {}).get("id")
                frm = str((cq.get("from") or {}).get("id"))
                if chat is None or not data.startswith("okapprove:"):
                    continue
                if self.allow and frm not in self.allow and not self.allow_all:  # auth POR CLICADOR
                    continue
                rest = data[len("okapprove:"):]                  # "yes" (antigo) | "<nonce>:yes" (P1.3)
                nonce, verdict = rest.rsplit(":", 1) if ":" in rest else ("", rest)
                cmd = "/yes" if verdict == "yes" else "/no"
                thr = cmsg.get("message_thread_id")              # tópico → casa com a sessão chat:thread
                cid_cb = f"{chat}:{thr}" if (cmsg.get("is_topic_message") and thr) else str(chat)
                out.append(Inbound("telegram", cid_cb, text=(f"{cmd}:{nonce}" if nonce else cmd)))
                continue
            msg = u.get("message") or {}
            chat = (msg.get("chat") or {}).get("id")
            if chat is None:
                continue
            mid = str(msg.get("message_id") or u.get("update_id") or "")
            # tópico de fórum → vira "chat:thread": o endpoint trata como conversa SEPARADA (auto).
            thr = msg.get("message_thread_id")
            cid = f"{chat}:{thr}" if (msg.get("is_topic_message") and thr) else str(chat)
            caption = msg.get("caption", "") or ""
            voice = msg.get("voice") or msg.get("audio")   # nota de voz ou áudio
            if voice and voice.get("file_id"):
                try:
                    audio = self.client.download_file(voice["file_id"])
                    out.append(Inbound("telegram", cid, text="", audio=audio, msg_id=mid))
                    continue
                except Exception:  # noqa: BLE001 — falhou o download → ignora o áudio
                    pass
            photo = msg.get("photo")                        # foto → vision (§6)
            if photo:
                try:
                    img = self.client.download_file(photo[-1]["file_id"])   # maior resolução
                    out.append(Inbound("telegram", cid, text=caption, image=img, msg_id=mid))
                    continue
                except Exception:  # noqa: BLE001
                    pass
            # documento/vídeo → baixa e entrega o CAMINHO ao agente (vai pro inbox do workspace).
            attach = msg.get("document") or msg.get("video") or msg.get("video_note") or msg.get("animation")
            if attach and attach.get("file_id"):
                name = attach.get("file_name") or "arquivo"
                if (attach.get("file_size") or 0) > _DOWNLOAD_MAX:   # getFile capa em 20MB → nem tenta
                    note = (f"[o usuário tentou enviar «{name}», mas o arquivo passa de 20MB e o "
                            "Telegram Bot API não deixa baixar — peça outro meio (link, split, etc.)]")
                    out.append(Inbound("telegram", cid, text=(f"{caption}\n{note}" if caption else note),
                                       msg_id=mid))
                    continue
                try:
                    fp = self.client.download_file(attach["file_id"])
                    out.append(Inbound("telegram", cid, text=caption, file=fp, file_name=name, msg_id=mid))
                    continue
                except Exception:  # noqa: BLE001
                    pass
            sticker = msg.get("sticker")                    # sticker estático (webp) → vision, como foto
            if sticker and sticker.get("file_id") and not sticker.get("is_animated") \
                    and not sticker.get("is_video"):
                try:
                    img = self.client.download_file(sticker["file_id"])
                    out.append(Inbound("telegram", cid, text=caption, image=img, msg_id=mid))
                    continue
                except Exception:  # noqa: BLE001
                    pass
            txt = msg.get("text")
            if txt:
                out.append(Inbound("telegram", cid, text=txt, msg_id=mid))
        return out

    def start(self) -> None:
        """No boot do gateway: registra o menu '/' do Telegram a partir do registro de comandos."""
        from okami import commands as _cmds
        self.client.set_my_commands(_cmds.telegram_menu())

    def send(self, chat_id, text: str) -> None:
        chat, thread = self._decode(chat_id)
        self.client.send_message(chat, text, thread=thread)

    def send_status(self, chat_id, text: str):
        """Manda a mensagem de status e devolve o message_id (p/ editar ao vivo). None se falhar."""
        chat, thread = self._decode(chat_id)
        res = self.client.send_message(chat, text, thread=thread)
        return ((res or {}).get("result") or {}).get("message_id")

    def edit_message(self, chat_id, msg_id, text: str) -> bool:
        chat, thread = self._decode(chat_id)
        return self.client.edit_message(chat, msg_id, text, thread=thread)

    def set_reaction(self, chat_id, message_id, emoji: str) -> None:
        chat, _ = self._decode(chat_id)                  # reação é no chat real (thread não se aplica)
        self.client.set_reaction(chat, message_id, emoji)

    def send_typing(self, chat_id) -> None:
        chat, thread = self._decode(chat_id)
        self.client.send_chat_action(chat, "typing", thread=thread)

    def send_approval(self, chat_id, text: str, nonce: str = "") -> None:
        chat, thread = self._decode(chat_id)
        self.client.send_approval(chat, text, nonce, thread=thread)

    def send_audio(self, chat_id, audio_path) -> None:
        chat, _ = self._decode(chat_id)
        self.client.send_audio(chat, audio_path)

    def send_media(self, chat_id, path, caption: str = "", voice: bool = False,
                   document: bool = False) -> None:
        chat, thread = self._decode(chat_id)               # tópico de fórum vai junto
        self.client.send_media(chat, path, caption=caption, thread=thread,
                               voice=voice, document=document)

    def allowed(self, chat_id) -> bool:
        # DENY-BY-DEFAULT: sem allowlist, NINGUÉM passa (a não ser allow_all explícito). Agente com
        # shell/tools/memória atrás de um bot público é perigoso → fail-closed. Tópico usa o chat real.
        chat, _ = self._decode(chat_id)
        if self.allow:
            return chat in self.allow
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
