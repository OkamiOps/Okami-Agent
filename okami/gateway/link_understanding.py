"""Compreensão de links (pesquisa #7 item 11) — link puro no chat vira resumo, sem gastar um turno LLM.

Quando a pessoa cola SÓ uma URL (sem pedir nada), o gateway abre a página e devolve um resumo
denso na hora — em vez de empurrar tudo pro modelo principal num turno caro. O trabalho pesado
(fetch + chunk + resumo) roda no modelo AUXILIAR barato (task 'extract'), reusando o `web_extract`
que já existe; a guarda anti-SSRF mora DENTRO do `web_extract` (valida URL pública antes de buscar).

PRINCÍPIO: best-effort e fail-open. Sem backend de resumo → cai no texto cru truncado; erro de rede
→ string de erro legível (nunca levanta). Nada de credencial vaza: o gateway redige antes de enviar.
"""
from __future__ import annotations

import re

# URL http(s) "nua" — tolera porta/caminho/query, para no primeiro espaço ou caractere de fechamento.
_URL_RX = re.compile(r"https?://[^\s<>\"'\)\]]+", re.IGNORECASE)


def detect_urls(text: str) -> list[str]:
    """Extrai as URLs http(s) de `text`, na ordem, sem duplicatas. Vazio p/ comando (começa com '/')
    ou texto sem URL — comando do gateway NUNCA é tratado como link."""
    if not text or not isinstance(text, str):
        return []
    if text.lstrip().startswith("/"):                 # /slash … → comando do gateway, não link
        return []
    out: list[str] = []
    for m in _URL_RX.finditer(text):
        u = m.group(0).rstrip(".,;:!?")               # tira pontuação final colada na URL
        if u and u not in out:
            out.append(u)
    return out


def is_pure_url(text: str) -> bool:
    """True se a mensagem é SÓ uma URL (eventualmente com espaços ao redor) — o caso de auto-resumo.
    Mensagem com URL + texto ('olha isso <url>') segue o fluxo normal (vira turno)."""
    if not text or not isinstance(text, str):
        return False
    urls = detect_urls(text)
    return len(urls) == 1 and text.strip() == urls[0]


def summarize_link(cfg, url: str, *, web_extract=None) -> str:
    """Abre `url` e devolve um resumo denso (via modelo auxiliar 'extract', como o web_extract tool).
    A guarda anti-SSRF está DENTRO do web_extract. `web_extract` injetável p/ teste. NUNCA levanta."""
    if not url or not isinstance(url, str):
        return ""
    if web_extract is None:                           # import preguiçoso: web é dep opcional do gateway
        from okami.integrations.web import web_extract as _we
        web_extract = _we

    summarize = None
    if cfg is not None:                               # resumo via modelo auxiliar barato (task 'extract')
        from okami.integrations.web import _EXTRACT_SUMMARIZE_PROMPT
        from okami.llm.aux import aux_complete

        def summarize(txt: str) -> str:
            return aux_complete(cfg, "extract", [
                {"role": "system", "content": _EXTRACT_SUMMARIZE_PROMPT},
                {"role": "user", "content": txt}], max_tokens=800)
    try:
        return web_extract(url, summarize=summarize) or ""
    except Exception as e:  # noqa: BLE001 — best-effort: rede/parse falhou → string legível, sem quebrar o poll
        return f"(não consegui abrir o link: {e})"
