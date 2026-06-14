"""Compreensão de links (pesquisa #7 item 11) — link puro vira resumo SEM gastar um turno LLM.

detect_urls extrai URLs e ignora comandos; summarize_link embrulha web_extract (SSRF guardado lá
dentro) usando o modelo auxiliar, sem run_task; e poll_once auto-resume uma mensagem que é só uma URL
(atrás da flag channels.link_understanding) sem disparar turno, enquanto texto normal segue pro handle.
"""
from __future__ import annotations

import tempfile

from okami.channels.base import Channel, Inbound
from okami.gateway import AgentEndpoint
from okami.gateway.link_understanding import detect_urls, is_pure_url, summarize_link


def test_detect_urls_extracts_and_dedupes():
    urls = detect_urls("olha https://exemplo.com/a e de novo https://exemplo.com/a fim")
    assert urls == ["https://exemplo.com/a"]
    multi = detect_urls("http://a.com e https://b.com/x?q=1")
    assert multi == ["http://a.com", "https://b.com/x?q=1"]


def test_detect_urls_ignores_commands_and_plain_text():
    assert detect_urls("/help https://x.com") == []     # comando do gateway NUNCA é link
    assert detect_urls("sem link aqui") == []
    assert detect_urls("") == []


def test_detect_urls_strips_trailing_punctuation():
    assert detect_urls("veja https://exemplo.com/pagina.") == ["https://exemplo.com/pagina"]


def test_is_pure_url():
    assert is_pure_url("  https://exemplo.com/x  ") is True
    assert is_pure_url("olha isso https://exemplo.com/x") is False   # URL + texto → não é puro
    assert is_pure_url("sem url") is False


def test_summarize_link_uses_web_extract_without_run_task():
    seen = {}

    def _fake_extract(url, *, summarize=None):
        seen["url"] = url
        seen["has_summarize"] = summarize is not None
        return "RESUMO: a página fala sobre X, Y e Z."

    out = summarize_link(cfg=None, url="https://exemplo.com/artigo", web_extract=_fake_extract)
    assert out == "RESUMO: a página fala sobre X, Y e Z."
    assert seen["url"] == "https://exemplo.com/artigo"
    # cfg None → sem sumarizador auxiliar (não força um modelo); ainda assim usa o web_extract
    assert seen["has_summarize"] is False


def test_summarize_link_never_raises():
    def _boom(url, *, summarize=None):
        raise RuntimeError("rede caiu")

    out = summarize_link(cfg=None, url="https://x.com", web_extract=_boom)
    assert "não consegui abrir o link" in out          # erro vira string legível, não exceção


# ---- poll_once: auto-resumo de URL pura, sem run_task ----

class _UrlChannel(Channel):
    name = "telegram"                                   # superfície remota (autorizada via allow)

    def __init__(self, inbox):
        self._inbox = inbox
        self.sent: list[tuple[str, str]] = []

    def poll(self):
        out, self._inbox = self._inbox, []
        return out

    def send(self, chat_id, text):
        self.sent.append((str(chat_id), text))

    def allowed(self, chat_id):
        return True


def _runner_should_not_run(cfg, ws, goal, **kw):
    raise AssertionError("run_task NÃO devia ser chamado para uma URL pura")


def _ep_with(inbox, cfg):
    ch = _UrlChannel(inbox)
    return AgentEndpoint("dev", cfg=cfg, ws=tempfile.mkdtemp(), channel=ch,
                         run_task=_runner_should_not_run, spawn=lambda fn: fn())


class _Cfg:
    channels = {"link_understanding": True}


def test_poll_pure_url_auto_summarizes_without_run_task(monkeypatch):
    import okami.gateway.link_understanding as lu
    monkeypatch.setattr(lu, "summarize_link",
                        lambda cfg, url, **kw: f"RESUMO de {url}: tudo certo.")
    inbox = [Inbound("telegram", "7", text="https://exemplo.com/post", msg_id="m1")]
    ep = _ep_with(inbox, cfg=_Cfg())
    ep.poll_once()                                       # não deve chamar run_task (runner explode se chamar)
    assert any("RESUMO de https://exemplo.com/post" in t for _, t in ep.channel.sent)


def test_poll_non_url_still_routes_to_handle(monkeypatch):
    routed = {}

    inbox = [Inbound("telegram", "7", text="me conta uma piada", msg_id="m2")]
    ep = _ep_with(inbox, cfg=_Cfg())
    monkeypatch.setattr(ep, "handle", lambda chat_id, text: routed.update(chat_id=str(chat_id), text=text))
    ep.poll_once()
    assert routed == {"chat_id": "7", "text": "me conta uma piada"}   # texto comum → handle (turno normal)


def test_poll_url_when_flag_off_routes_to_handle(monkeypatch):
    """Sem a flag channels.link_understanding, uma URL pura segue o fluxo normal (vira turno)."""
    routed = {}

    class _CfgOff:
        channels = {}

    inbox = [Inbound("telegram", "7", text="https://exemplo.com/x", msg_id="m3")]
    ep = _ep_with(inbox, cfg=_CfgOff())
    monkeypatch.setattr(ep, "handle", lambda chat_id, text: routed.update(chat_id=str(chat_id), text=text))
    ep.poll_once()
    assert routed == {"chat_id": "7", "text": "https://exemplo.com/x"}   # flag off → handle, não auto-resumo
