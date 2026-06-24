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
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://(?:[^)\s]|\)(?!\s|$))+)\)")  # '(' interno (ex.: wiki) não trunca a URL
_HEADER = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)
# blockquote: rodado APÓS o escape → casa o '>' já como '&gt;'. Agrupa linhas '> ' consecutivas.
_QUOTE_LINE = re.compile(r"(?:^&gt;[ \t]?.*(?:\n|$))+", re.M)


def _quote_block(m: re.Match) -> str:
    inner = "\n".join(re.sub(r"^&gt;[ \t]?", "", ln) for ln in m.group(0).rstrip("\n").split("\n"))
    # citação LONGA (>4 linhas) → expandable: o Telegram colapsa e o usuário expande se quiser (paridade
    # Hermes; sem isso um quote gigante toma a tela toda no celular).
    tag = "blockquote expandable" if inner.count("\n") >= 4 else "blockquote"
    return f"<{tag}>{inner}</blockquote>\n"


# task list GFM: '- [ ] x' → '☐ x', '- [x] x' → '☑ x' (paridade Hermes, adaptado ao HTML; roda ANTES do
# bullet p/ consumir o '- [ ] ' e não virar '• [ ] x'). ☐/☑ são BMP → renderizam limpo no Telegram.
_TASK = re.compile(r"^([ \t]*)[-*+][ \t]+\[([ xX])\][ \t]+", re.M)
_BULLET = re.compile(r"^([ \t]*)[-*+][ \t]+(?=\S)", re.M)   # '- '/'* '/'+ ' no início → '• ' (não toca **/---)


def _tasklist(text: str) -> str:
    return _TASK.sub(lambda m: f"{m.group(1)}{'☑' if m.group(2) in 'xX' else '☐'} ", text)
_SEP_ROW = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")   # linha separadora de tabela (|---|:--:|)


def _bulletize(text: str) -> str:
    """Bullets markdown (-/*/+) viram '• ' (Hermes), preservando indentação. Não casa **bold** (char +
    char != espaço) nem hr '---' (char + char). Itálico '*x*' tampouco (precisa de espaço após o marcador)."""
    return _BULLET.sub(lambda m: f"{m.group(1)}• ", text)


def _row_cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _md_tables_to_kv(text: str) -> str:
    """Tabela markdown → bullets 'rótulo: valor' (Telegram não tem tabela; paridade Hermes adapter.py). Um
    bloco = linha de cabeçalho com '|', linha separadora '|---|', e ≥1 linha de dados. Vira uma linha por
    registro: '• **Col1:** v1 · **Col2:** v2'. Conteúdo fora de tabela passa intacto."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if ("|" in ln and i + 1 < n and _SEP_ROW.match(lines[i + 1]) and lines[i + 1].count("-") >= 1):
            headers = _row_cells(ln)
            j = i + 2
            rows = []
            while j < n and "|" in lines[j] and lines[j].strip():
                rows.append(_row_cells(lines[j]))
                j += 1
            if rows:                                       # tabela válida → renderiza key:value
                for cells in rows:
                    pairs = [f"**{headers[k]}:** {cells[k]}" if k < len(headers) and headers[k] else cells[k]
                             for k in range(len(cells)) if cells[k]]
                    out.append("• " + " · ".join(pairs))
                i = j
                continue
        out.append(ln)
        i += 1
    return "\n".join(out)


def _html_to_md(text: str) -> str:
    """O modelo MUITAS vezes manda HTML cru (`<b>`, `<code>`…) — por hábito ou porque era instruído a
    isso. Sem normalizar, o html.escape transforma `<b>` em `&lt;b&gt;` e o usuário vê a TAG literal
    (o bug do FIPE). Converte as tags do Telegram p/ markdown ANTES do pipeline; tag não-suportada
    (div/span/li/h1…) perde só a tag (conteúdo fica) p/ a API não recusar o parse. `<` solto de prosa
    ('2 < 3') não casa nenhuma tag → segue pro escape normal."""
    t = text
    t = re.sub(r'<a\s+href=(["\'])(.*?)\1[^>]*>(.*?)</a>', r'[\3](\2)', t, flags=re.I | re.S)
    t = re.sub(r'<pre>\s*<code[^>]*>(.*?)</code>\s*</pre>', lambda m: f"```\n{m.group(1)}\n```", t, flags=re.I | re.S)
    t = re.sub(r'<pre[^>]*>(.*?)</pre>', lambda m: f"```\n{m.group(1)}\n```", t, flags=re.I | re.S)
    t = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', t, flags=re.I | re.S)
    t = re.sub(r'<blockquote>(.*?)</blockquote>',
               lambda m: "\n".join("> " + ln for ln in m.group(1).strip().split("\n")), t, flags=re.I | re.S)
    t = re.sub(r'</?(?:b|strong)\s*>', '**', t, flags=re.I)
    t = re.sub(r'</?(?:i|em)\s*>', '_', t, flags=re.I)
    t = re.sub(r'</?(?:s|del|strike)\s*>', '~~', t, flags=re.I)
    t = re.sub(r'</?tg-spoiler\s*>', '||', t, flags=re.I)
    t = re.sub(r'<br\s*/?>', '\n', t, flags=re.I)
    t = re.sub(r'</?p\s*>', '\n', t, flags=re.I)
    t = re.sub(r'</?(?:div|span|ul|ol|li|h[1-6]|table|tr|td|th|tbody|thead)[^>]*>', '', t, flags=re.I)
    return t


def to_html(md: str) -> str:
    """Converte um subconjunto de markdown p/ as tags HTML que o Telegram aceita: <b> <i> <s> <code>
    <pre> <a> <tg-spoiler> <blockquote>. Conteúdo de código é protegido (não formata por dentro).
    Tolera HTML cru do modelo (normaliza p/ markdown antes) — assim `<b>` renderiza em vez de virar tag
    literal pro usuário."""
    text = _html_to_md(md or "")
    stash: dict[str, str] = {}

    def _keep(rendered: str) -> str:
        key = f"\x00TGHTML{len(stash)}\x00"
        stash[key] = rendered
        return key

    # 1) CÓDIGO PRIMEIRO — ANTES de tabela/bullet — senão uma tabela ou lista mostrada DENTRO de um bloco
    #    ```…``` (exemplo de código) era convertida em bullet/'rótulo: valor' e o exemplo virava lixo (bug).
    def _fence(m: re.Match) -> str:
        lang = m.group(1).strip()
        body = html.escape(m.group(2).strip("\n"), quote=False)
        cls = f' class="language-{lang}"' if lang else ""
        return _keep(f"<pre><code{cls}>{body}</code></pre>")

    text = _FENCE.sub(_fence, text)
    text = _INLINE_CODE.sub(lambda m: _keep(f"<code>{html.escape(m.group(1), quote=False)}</code>"), text)
    # 2) AGORA tabela → bullets 'rótulo: valor' + bullets -/*/+ → •  (o código já saiu, protegido na stash)
    text = _md_tables_to_kv(text)          # tabela → bullets (Telegram não tem tabela)
    text = _tasklist(text)                 # - [ ]/[x] → ☐/☑ (ANTES do bullet, consome o marcador)
    text = _bulletize(text)                # -/*/+ → • (o • literal sobrevive ao escape)
    # 3) escapa o texto normal (&<>) — as tags que NÓS geramos entram depois disso
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


def to_plain(md: str) -> str:
    """Versão TEXTO-PURO legível (sem markup): normaliza+renderiza e tira as tags + desescapa entidades.
    Fallback quando o Telegram recusa o HTML — o usuário vê 'negrito', não '**negrito**' nem '<b>'."""
    stripped = re.sub(r"<[^>]+>", "", to_html(md))
    return html.unescape(stripped)
