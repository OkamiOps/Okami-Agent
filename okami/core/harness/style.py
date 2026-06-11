"""Bloco de ESTILO da resposta — VISÍVEL no system prompt (não escondido no manual interno).

Dor real (modelos fracos curtos/sem formatação): a orientação de markdown/idioma vivia dentro do
bloco "=== COMO VOCÊ AGE · NUNCA cite" → o modelo tratava como ruído a evitar. Aqui ela é positiva e
visível ("é o que a pessoa vê, capricha"), e adapta o FORMATO ao canal (Telegram não tem tabela pipe,
Slack usa mrkdwn, CLI/TUI renderiza tabela/seção). Espelhar o idioma da pessoa vale em todo canal."""

from __future__ import annotations

# Superfícies que renderizam tabela markdown de verdade (CLI/TUI) → mantêm o esqueleto com tabela.
_RICH_MARKDOWN = {"cli", "tui", "subagent", "terminal", "api"}

# Hint de FORMATO por canal: o que cada superfície renderiza (e o que NÃO renderiza).
_SURFACE_HINT = {
    "telegram": ("FORMATO NESTE CANAL (Telegram): use **negrito**, _itálico_, `código`, blocos ``` e "
                 "listas com `-`. O Telegram NÃO tem tabela — em vez de tabela markdown, use lista com "
                 "`rótulo: valor`. Cabeçalhos `##` viram negrito. Seja claro e direto."),
    "slack": ("FORMATO NESTE CANAL (Slack/mrkdwn): *negrito* com um asterisco, _itálico_, `código`, "
              "blocos ``` e listas com `-`. Slack NÃO tem tabela — use lista com `rótulo: valor`."),
    "discord": ("FORMATO NESTE CANAL (Discord): **negrito**, *itálico*, `código`, blocos ``` e listas. "
                "Sem tabela rica — prefira lista com `rótulo: valor`."),
    "mattermost": ("FORMATO NESTE CANAL (Mattermost): markdown padrão (negrito/itálico/código/listas). "
                   "Sem tabela pipe garantida — prefira lista com `rótulo: valor`."),
    "group": ("FORMATO NESTE CANAL (grupo): seja CONCISO — é conversa com várias pessoas. Markdown leve "
              "(negrito/itálico/código/listas), sem paredão e sem tabela pipe."),
}


def _delivery_full() -> str:
    """Esqueleto de entrega COM tabela — superfícies que renderizam markdown rico (CLI/TUI)."""
    return """<entrega>
A resposta final vai INTEIRA e ESTRUTURADA em MARKDOWN — a TUI renderiza tabela, seção e cor; texto
corrido num parágrafo único fica FEIO e ilegível (é a entrega ruim). REGRAS DE FORMATO, sempre:
- Seções com `## Título` e LINHA EM BRANCO entre elas. NUNCA um parágrafo gigante.
- COMPARAÇÃO → TABELA markdown (`| aspecto | A | B | C |`, uma linha por aspecto), nunca prosa.
- TESTES → TABELA (`| suíte | passou | falhou |`) + a LISTA das falhas reais (qual teste/erro), não só "X/Y".
- ITENS/BUGS → lista `- **nome** (`arquivo:linha`) — porquê` (+ o fix se pediram).
ESQUELETO de um relatório (preencha com o REAL; corte seção que não se aplica; adapte ao pedido):

## <título curto>
### Resumo
<2–3 linhas, no SEU tom>
### Testes rodados
| suíte | passou | falhou |
|---|---|---|
| … | … | … |
### Comparação
| aspecto | Okami | Hermes | OpenClaw |
|---|---|---|---|
| … | … | … | … |
### Achados (arquivo:linha)
- **<achado>** (`arquivo:linha`) — <porquê>

PROIBIDO: parágrafo corrido sem seções/tabela; "relatório no chat" / "segue acima" / "entregue antes"
(over-claim); jogar o conteúdo só na memória e mandar resumo. Se não está ESCRITO e ESTRUTURADO aqui,
não existe.
</entrega>"""


def _delivery_bullets() -> str:
    """Esqueleto de entrega SEM tabela — canais que não renderizam tabela pipe (Telegram/Slack/…)."""
    return """<entrega>
A resposta final vai INTEIRA e ESTRUTURADA — texto corrido num parágrafo único fica ilegível (é a
entrega ruim). REGRAS DE FORMATO neste canal (sem tabela pipe):
- Seções com `## Título` (ou negrito) e LINHA EM BRANCO entre elas. NUNCA um parágrafo gigante.
- COMPARAÇÃO/DADOS → lista com `rótulo: valor` (uma linha por item), NÃO tabela markdown.
- TESTES → lista das falhas reais (qual teste/erro) + o placar, não só "X/Y".
- ITENS/BUGS → lista `- **nome** (`arquivo:linha`) — porquê` (+ o fix se pediram).
PROIBIDO: parágrafo corrido sem seções; "segue acima" / "entregue antes" (over-claim); jogar o conteúdo
só na memória e mandar resumo. Se não está ESCRITO e ESTRUTURADO aqui, não existe.
</entrega>"""


_LANGUAGE = """<idioma>
Responda SEMPRE no MESMO idioma da ÚLTIMA mensagem da pessoa: escreveu em inglês → responda em inglês;
em português → português; em espanhol → espanhol. Espelhe o idioma dela a CADA turno. Sua identidade
(SOUL/VOICE) pode estar em português, mas a LÍNGUA da resposta segue a da pessoa — NUNCA force português
numa conversa em inglês (nem o contrário). Na dúvida ou 1ª mensagem, use o idioma em que ela te escreveu.
</idioma>"""


def style_block(surface: str = "cli") -> str:
    """Orientação de ESTILO da resposta (markdown + idioma + formato do canal). Visível no prompt."""
    surf = (surface or "cli").lower()
    delivery = _delivery_full() if surf in _RICH_MARKDOWN or surf not in _SURFACE_HINT else _delivery_bullets()
    hint = _SURFACE_HINT.get(surf, "")
    parts = ["COMO ESCREVER PRA PESSOA (isto é o que ela vê na resposta final — capriche no formato):",
             delivery, _LANGUAGE]
    if hint:
        parts.append(hint)
    return "\n".join(parts)
