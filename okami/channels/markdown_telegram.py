"""Markdown → HTML do Telegram (estilo Hermes, simplificado): o agente escreve markdown comum e o
canal entrega FORMATADO (negrito/itálico/código/link) em vez de asteriscos literais.

HTML em vez de MarkdownV2 de propósito: o MarkdownV2 exige escapar 18 caracteres no TEXTO (qualquer
'.' ou '-' cru quebra o parse); no HTML só &<> — bem mais robusto p/ texto vindo de modelo. Quem
chama (TelegramClient.send_message) ainda tem fallback p/ texto puro se a API recusar o parse."""

from __future__ import annotations

import html
import re

_FENCE = re.compile(r"```([A-Za-z0-9_+-]*)\n?(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_UND_BOLD = re.compile(r"__(.+?)__", re.S)                 # __x__ → negrito (antes do itálico _x_)
_STAR_ITALIC = re.compile(r"\*([^*\n]+)\*")
# _itálico_ só com fronteira de palavra: snake_case_nome não vira itálico.
_UND_ITALIC = re.compile(r"(?<![\w_])_([^_\n]+)_(?![\w_])")
_STRIKE = re.compile(r"~~(.+?)~~", re.S)
_SPOILER = re.compile(r"\|\|(.+?)\|\|", re.S)              # ||x|| → spoiler (Telegram <tg-spoiler>)
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_HEADER = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)
# blockquote: rodado APÓS o escape → casa o '>' já como '&gt;'. Agrupa linhas '> ' consecutivas.
_QUOTE_LINE = re.compile(r"(?:^&gt;[ \t]?.*(?:\n|$))+", re.M)


def _quote_block(m: re.Match) -> str:
    inner = "\n".join(re.sub(r"^&gt;[ \t]?", "", ln) for ln in m.group(0).rstrip("\n").split("\n"))
    return f"<blockquote>{inner}</blockquote>\n"


def to_html(md: str) -> str:
    """Converte um subconjunto de markdown p/ as tags HTML que o Telegram aceita: <b> <i> <s> <code>
    <pre> <a> <tg-spoiler> <blockquote>. Conteúdo de código é protegido (não formata por dentro)."""
    text = md or ""
    stash: dict[str, str] = {}

    def _keep(rendered: str) -> str:
        key = f"\x00TGHTML{len(stash)}\x00"
        stash[key] = rendered
        return key

    # 1) código primeiro (fence e inline): escapa o CONTEÚDO e protege de formatação posterior
    def _fence(m: re.Match) -> str:
        lang = m.group(1).strip()
        body = html.escape(m.group(2).strip("\n"), quote=False)
        cls = f' class="language-{lang}"' if lang else ""
        return _keep(f"<pre><code{cls}>{body}</code></pre>")

    text = _FENCE.sub(_fence, text)
    text = _INLINE_CODE.sub(lambda m: _keep(f"<code>{html.escape(m.group(1), quote=False)}</code>"), text)
    # 2) escapa o texto normal (&<>) — as tags que NÓS geramos entram depois disso
    text = html.escape(text, quote=False)
    # 3) formatação (ordem: link → negrito ** e __ → itálico * e _ → riscado → spoiler → header)
    text = _LINK.sub(r'<a href="\2">\1</a>', text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _UND_BOLD.sub(r"<b>\1</b>", text)
    text = _STAR_ITALIC.sub(r"<i>\1</i>", text)
    text = _UND_ITALIC.sub(r"<i>\1</i>", text)             # roda depois do negrito → **_x_** aninha certo
    text = _STRIKE.sub(r"<s>\1</s>", text)
    text = _SPOILER.sub(r"<tg-spoiler>\1</tg-spoiler>", text)
    text = _HEADER.sub(r"<b>\1</b>", text)
    # 4) blockquote: agrupa linhas '&gt; ' consecutivas num só <blockquote> (Telegram suporta)
    text = _QUOTE_LINE.sub(_quote_block, text).rstrip("\n") if "&gt;" in text else text
    # 5) devolve os trechos de código protegidos
    for key, rendered in stash.items():
        text = text.replace(key, rendered)
    return text
