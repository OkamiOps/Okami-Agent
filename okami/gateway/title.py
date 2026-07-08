"""Título automático da sessão (paridade Hermes agent/title_generator.py) — só a geração PURA;
o disparo fire-and-forget (thread) + persistência ficam no endpoint (mesmo padrão de _maybe_compact,
que já usa aux_complete em fundo pra não atrasar o turno)."""

from __future__ import annotations

_TITLE_PROMPT = (
    "Gere um título CURTO (3 a 7 palavras) pra esta conversa, no MESMO idioma da mensagem do usuário. "
    "Devolva SOMENTE o título — sem aspas, sem pontuação final, sem prefixos como 'Título:'."
)


def generate_title(cfg, user_text: str, assistant_text: str) -> str:
    """Pede ao modelo AUXILIAR (barato/fundo — item 57) um título de 3-7 palavras a partir da 1ª troca
    da conversa. Best-effort: qualquer falha (provider fora, cfg incompleta) devolve "" — título é
    cosmético (aparece no /status e /sessions) e NUNCA pode derrubar ou atrasar o turno."""
    from okami.llm.aux import aux_complete
    u = (user_text or "").strip()[:500]
    a = (assistant_text or "").strip()[:500]
    if not u and not a:
        return ""
    try:
        title = aux_complete(cfg, "title", [
            {"role": "system", "content": _TITLE_PROMPT},
            {"role": "user", "content": f"User: {u}\n\nAssistant: {a}"},
        ], max_tokens=60)
    except Exception:  # noqa: BLE001 — best-effort
        return ""
    return _clean_title(title)


def _clean_title(raw: str) -> str:
    title = (raw or "").strip()
    for tag in ("<think>", "</think>"):          # alguns modelos vazam raciocínio mesmo em max_tokens baixo
        if tag in title:
            title = title.split(tag)[-1].strip() if tag == "</think>" else title.split(tag)[0].strip()
    title = title.strip().strip('"\'“”‘’').strip()
    for prefix in ("título:", "title:"):
        if title.lower().startswith(prefix):
            title = title[len(prefix):].strip()
    title = title.rstrip(".!?").strip()
    if len(title) > 80:
        title = title[:77].rstrip() + "..."
    return title
