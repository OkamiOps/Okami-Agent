"""Mídia no Telegram (paridade Hermes): MEDIA:<path> na resposta do agente → anexo nativo
(sendPhoto/sendDocument/sendVideo/sendVoice/sendAudio/sendAnimation), e entrada de
documento/vídeo/sticker. Antes o agente NÃO conseguia enviar arquivo nenhum pelo Telegram."""

from __future__ import annotations

import tempfile
from pathlib import Path

from okami.channels.base import Channel
from okami.channels.media import Media, extract_media
from okami.channels.telegram import TelegramChannel, TelegramClient
from okami.core import Task, TaskState
from okami.gateway import AgentEndpoint


# ----------------------------------------------------------------- extração MEDIA:<path>
def test_extract_media_basic():
    clean, media = extract_media("Aqui está o relatório:\n\nMEDIA:/tmp/rel.pdf\n\nQualquer dúvida me fala.")
    assert media == [Media("/tmp/rel.pdf")]
    assert "MEDIA:" not in clean and "rel.pdf" not in clean
    assert "Aqui está o relatório:" in clean and "Qualquer dúvida" in clean


def test_extract_media_quoted_path_with_spaces():
    clean, media = extract_media('Segue: MEDIA:"/tmp/meu arquivo final.png"')
    assert media == [Media("/tmp/meu arquivo final.png")]
    assert "MEDIA:" not in clean


def test_extract_media_tilde_expands():
    _, media = extract_media("MEDIA:~/docs/x.pdf")
    assert media and media[0].path == str(Path("~/docs/x.pdf").expanduser())


def test_extract_media_multiple():
    _, media = extract_media("MEDIA:/a/um.png e depois MEDIA:/b/dois.zip")
    assert [m.path for m in media] == ["/a/um.png", "/b/dois.zip"]


def test_extract_media_ignores_code_blocks():
    text = "Use assim:\n```\nMEDIA:/tmp/exemplo.pdf\n```\ne inline `MEDIA:/tmp/outro.pdf` também."
    clean, media = extract_media(text)
    assert media == []                                    # dentro de código NÃO é diretiva
    assert "MEDIA:/tmp/exemplo.pdf" in clean and "MEDIA:/tmp/outro.pdf" in clean


def test_extract_media_unknown_extension_not_extracted():
    clean, media = extract_media("MEDIA:/tmp/binario.xyz123")
    assert media == [] and "binario.xyz123" in clean      # extensão desconhecida fica no texto


def test_extract_media_voice_directive():
    clean, media = extract_media("[[audio_as_voice]]\nMEDIA:/tmp/fala.ogg")
    assert media == [Media("/tmp/fala.ogg", voice=True)]
    assert "[[audio_as_voice]]" not in clean


def test_extract_media_as_document_directive():
    clean, media = extract_media("[[as_document]]\nMEDIA:/tmp/print.png")
    assert media == [Media("/tmp/print.png", document=True)]
    assert "[[as_document]]" not in clean


# ----------------------------------------------------------------- roteamento por extensão
def _client_capturing(monkeypatch):
    c = TelegramClient("tok")
    calls: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(c, "_call_multipart",
                        lambda method, params, field, path, **k:
                        (calls.append((method, field, dict(params))), {"ok": True})[1])
    monkeypatch.setattr("okami.channels.telegram._file_size", lambda p: 1024)
    return c, calls


def test_send_media_routes_by_extension(monkeypatch):
    c, calls = _client_capturing(monkeypatch)
    for path, method, field in [
        ("/t/a.png", "sendPhoto", "photo"),
        ("/t/a.jpg", "sendPhoto", "photo"),
        ("/t/a.gif", "sendAnimation", "animation"),
        ("/t/a.mp4", "sendVideo", "video"),
        ("/t/a.mp3", "sendAudio", "audio"),
        ("/t/a.m4a", "sendAudio", "audio"),
        ("/t/a.pdf", "sendDocument", "document"),
        ("/t/a.py", "sendDocument", "document"),
        ("/t/a.ogg", "sendDocument", "document"),     # ogg sem [[audio_as_voice]] → documento
    ]:
        calls.clear()
        c.send_media("1", path)
        assert calls and calls[0][:2] == (method, field), path


def test_send_media_voice_flag_routes_ogg_to_voice(monkeypatch):
    c, calls = _client_capturing(monkeypatch)
    c.send_media("1", "/t/fala.ogg", voice=True)
    assert calls[0][:2] == ("sendVoice", "voice")


def test_send_media_as_document_forces_document(monkeypatch):
    c, calls = _client_capturing(monkeypatch)
    c.send_media("1", "/t/foto.png", document=True)
    assert calls[0][:2] == ("sendDocument", "document")


def test_send_media_caption_and_thread(monkeypatch):
    c, calls = _client_capturing(monkeypatch)
    c.send_media("1", "/t/a.pdf", caption="x" * 2000, thread=7)
    _, _, params = calls[0]
    assert len(params["caption"]) == 1024                 # limite do Telegram
    assert params["message_thread_id"] == 7


def test_send_media_big_photo_falls_back_to_document(monkeypatch):
    c, calls = _client_capturing(monkeypatch)
    monkeypatch.setattr("okami.channels.telegram._file_size", lambda p: 11 * 1024 * 1024)
    c.send_media("1", "/t/foto.png")                      # >10MB não pode ser sendPhoto
    assert calls[0][:2] == ("sendDocument", "document")


def test_send_media_over_upload_limit_raises(monkeypatch):
    import pytest
    c, _ = _client_capturing(monkeypatch)
    monkeypatch.setattr("okami.channels.telegram._file_size", lambda p: 51 * 1024 * 1024)
    with pytest.raises(ValueError):
        c.send_media("1", "/t/grande.zip")                # >50MB: Bot API não aceita upload


def test_send_media_photo_api_error_falls_back_to_document(monkeypatch):
    import urllib.error
    c = TelegramClient("tok")
    calls: list[str] = []

    def fake(method, params, field, path, **k):
        calls.append(method)
        if method == "sendPhoto":                         # ex.: dimensões inválidas p/ foto
            raise urllib.error.HTTPError("u", 400, "bad photo", {}, None)
        return {"ok": True}

    monkeypatch.setattr(c, "_call_multipart", fake)
    monkeypatch.setattr("okami.channels.telegram._file_size", lambda p: 1024)
    c.send_media("1", "/t/foto.png")
    assert calls == ["sendPhoto", "sendDocument"]


def test_call_multipart_builds_body(monkeypatch, tmp_path):
    import io
    import json as _json
    import urllib.request
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-fake")
    cap = {}

    def fake_urlopen(req, timeout=0):
        cap["url"] = req.full_url
        cap["body"] = req.data
        cap["ctype"] = req.get_header("Content-type")
        return io.BytesIO(_json.dumps({"ok": True, "result": {"message_id": 1}}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = TelegramClient("tok")
    res = c._call_multipart("sendDocument", {"chat_id": "9", "caption": "oi"}, "document", str(f))
    assert res["ok"] and cap["url"].endswith("/sendDocument")
    assert "multipart/form-data" in cap["ctype"]
    assert b"%PDF-fake" in cap["body"] and b'name="chat_id"' in cap["body"] and b'name="caption"' in cap["body"]
    assert b'filename="doc.pdf"' in cap["body"]


def test_channel_send_media_decodes_topic(monkeypatch):
    ch = TelegramChannel("tok")
    cap = {}
    monkeypatch.setattr(ch.client, "send_media",
                        lambda chat, path, caption="", thread=None, voice=False, document=False:
                        cap.update(chat=chat, thread=thread, path=path))
    assert ch.supports_media
    ch.send_media("99:7", "/t/a.pdf")
    assert cap == {"chat": "99", "thread": 7, "path": "/t/a.pdf"}


# ----------------------------------------------------------------- entrada: documento/vídeo/sticker
def _poll_one(monkeypatch, message: dict, downloaded="/tmp/baixado.bin"):
    ch = TelegramChannel("tok", allow_all=True)
    monkeypatch.setattr(ch.client, "get_updates",
                        lambda **k: [{"update_id": 1, "message": message}])
    monkeypatch.setattr(ch.client, "download_file", lambda fid: downloaded)
    return ch.poll()


def test_poll_document_inbound(monkeypatch):
    inb = _poll_one(monkeypatch, {"message_id": 5, "chat": {"id": 9},
                                  "document": {"file_id": "F", "file_name": "rel.pdf", "file_size": 1000},
                                  "caption": "resumo isso"}, downloaded="/tmp/d.pdf")
    assert len(inb) == 1
    m = inb[0]
    assert m.file == "/tmp/d.pdf" and m.file_name == "rel.pdf"
    assert m.text == "resumo isso" and m.chat_id == "9" and m.msg_id == "5"


def test_poll_video_inbound(monkeypatch):
    inb = _poll_one(monkeypatch, {"message_id": 6, "chat": {"id": 9},
                                  "video": {"file_id": "V", "file_size": 1000}}, downloaded="/tmp/v.mp4")
    assert len(inb) == 1 and inb[0].file == "/tmp/v.mp4"


def test_poll_document_too_large_becomes_notice(monkeypatch):
    called = {"n": 0}
    ch = TelegramChannel("tok", allow_all=True)
    msg = {"message_id": 7, "chat": {"id": 9},
           "document": {"file_id": "F", "file_name": "big.iso", "file_size": 25 * 1024 * 1024}}
    monkeypatch.setattr(ch.client, "get_updates", lambda **k: [{"update_id": 1, "message": msg}])
    monkeypatch.setattr(ch.client, "download_file",
                        lambda fid: called.__setitem__("n", called["n"] + 1))
    inb = ch.poll()
    assert called["n"] == 0                               # getFile capa em 20MB → nem tenta
    assert len(inb) == 1 and inb[0].file is None and "big.iso" in inb[0].text


def test_poll_static_sticker_becomes_image(monkeypatch):
    inb = _poll_one(monkeypatch, {"message_id": 8, "chat": {"id": 9},
                                  "sticker": {"file_id": "S", "is_animated": False, "is_video": False}},
                    downloaded="/tmp/s.webp")
    assert len(inb) == 1 and inb[0].image == "/tmp/s.webp"


def test_poll_photo_carries_msg_id_and_topic(monkeypatch):
    inb = _poll_one(monkeypatch, {"message_id": 11, "chat": {"id": 9}, "is_topic_message": True,
                                  "message_thread_id": 3, "photo": [{"file_id": "P"}],
                                  "caption": "olha"}, downloaded="/tmp/p.jpg")
    assert len(inb) == 1
    assert inb[0].chat_id == "9:3" and inb[0].msg_id == "11" and inb[0].image == "/tmp/p.jpg"


# ----------------------------------------------------------------- gateway: entrega fim-a-fim
class MediaChannel(Channel):
    name = "fake-media"
    supports_media = True

    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.media: list[tuple[str, str, dict]] = []

    def poll(self):
        return []

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def send_media(self, chat_id, path, caption="", voice=False, document=False):
        self.media.append((str(chat_id), str(path), {"voice": voice, "document": document}))

    def allowed(self, chat_id):
        return True


def _media_ep(reply: str, channel=None, capture=None):
    def runner(cfg, ws, goal, *, extra_context="", **kw):
        if capture is not None:
            capture["ctx"] = extra_context
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, reply
        return t

    ch = channel or MediaChannel()
    return AgentEndpoint("dev", cfg=None, ws=tempfile.mkdtemp(), channel=ch,
                         run_task=runner, spawn=lambda fn: fn())


def test_run_delivers_media_and_clean_text():
    ep = _media_ep("Pronto, segue o PDF:\n\nMEDIA:/tmp/rel.pdf")
    ep.handle("7", "gera o relatório")
    assert ("7", "/tmp/rel.pdf") in [(c, p) for c, p, _ in ep.channel.media]
    assert all("MEDIA:" not in t for _, t in ep.channel.sent)     # tag não vaza pro usuário
    assert any("segue o PDF" in t for _, t in ep.channel.sent)


def test_run_media_only_reply_skips_empty_text():
    ep = _media_ep("MEDIA:/tmp/foto.png")
    ep.handle("7", "manda a foto")
    assert ep.channel.media and ep.channel.media[0][1] == "/tmp/foto.png"
    sent = [t for _, t in ep.channel.sent]
    assert not any(t.strip() in {"", "✅", "✅ "} for t in sent)   # não manda mensagem vazia


def test_run_media_failure_falls_back_to_text_note():
    class Failing(MediaChannel):
        def send_media(self, chat_id, path, caption="", voice=False, document=False):
            raise RuntimeError("arquivo não existe")

    ep = _media_ep("MEDIA:/tmp/sumiu.pdf", channel=Failing())
    ep.handle("7", "manda")
    assert any("sumiu.pdf" in t for _, t in ep.channel.sent)      # avisa, não engole


def test_media_hint_injected_only_when_supported():
    cap: dict = {}
    ep = _media_ep("ok", capture=cap)
    ep.handle("7", "oi")
    assert "MEDIA:" in cap.get("ctx", "")                          # canal com mídia → agente sabe a sintaxe

    class NoMedia(Channel):
        name = "fake"

        def __init__(self):
            self.sent = []

        def poll(self):
            return []

        def send(self, chat_id, text):
            self.sent.append((str(chat_id), text))

    cap2: dict = {}
    ep2 = _media_ep("ok", channel=NoMedia(), capture=cap2)
    ep2.handle("7", "oi")
    assert "MEDIA:" not in cap2.get("ctx", "")                     # canal sem mídia → sem ruído no prompt


def test_poll_once_file_lands_in_inbox(tmp_path):
    src = tmp_path / "contrato.pdf"
    src.write_bytes(b"%PDF")
    from okami.channels.base import Inbound

    class FileChannel(MediaChannel):
        def __init__(self):
            super().__init__()
            self._q = [Inbound("fake-media", "7", text="revisa isso",
                               file=str(src), file_name="contrato.pdf", msg_id="1")]

        def poll(self):
            q, self._q = self._q, []
            return q

    got = {}

    def runner(cfg, ws, goal, **kw):
        got["goal"] = goal
        t = Task(goal=goal)
        t.state, t.result = TaskState.COMPLETE, "li"
        return t

    ws = tempfile.mkdtemp()
    ep = AgentEndpoint("dev", cfg=None, ws=ws, channel=FileChannel(),
                       run_task=runner, spawn=lambda fn: fn())
    ep.poll_once()
    assert "revisa isso" in got["goal"] and "inbox/contrato.pdf" in got["goal"]
    assert (Path(ws) / "inbox" / "contrato.pdf").read_bytes() == b"%PDF"
