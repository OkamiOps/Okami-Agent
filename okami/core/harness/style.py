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
    "telegram": ("FORMATO NESTE CANAL (Telegram, vira HTML de verdade): **negrito**, _itálico_, ~~riscado~~, "
                 "`código`, blocos ```lang … ```, [link](url), `> citação` (blockquote), `||spoiler||`, e "
                 "listas com `-`. O Telegram NÃO tem tabela — em vez de tabela markdown, use lista com "
                 "`rótulo: valor`. Cabeçalhos `##` viram negrito. Capriche no formato; seja claro e direto."),
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


# Guidance por FAMÍLIA de modelo (Hermes prompt_builder: blocos condicionais por nome do modelo).
# Curto de propósito — só o que muda a mania daquela família. Forte (Claude) segue instrução → sem bloco.
_FAMILY_OPENAI = ("AFINADO PRO SEU MODELO: aja, não prometa — se disse que vai rodar/ler/criar, FAÇA a "
                  "tool call no MESMO turno. Cheque o pré-requisito antes (existe? instalado?), e VERIFIQUE "
                  "o resultado com tool antes de afirmar 'pronto'. Não pergunte o que dá pra descobrir sozinho.")
_FAMILY_GEMINI = ("AFINADO PRO SEU MODELO: seja CONCISO — poucas frases, foco em ação e resultado, não "
                  "narração. Use CAMINHO ABSOLUTO nas ferramentas; rode leituras independentes em PARALELO "
                  "(um lote); flags não-interativas no shell (-y/--no-input).")
_FAMILY_WEAK_OPEN = ("AFINADO PRO SEU MODELO: emita UMA ação por turno — um único bloco ```json "
                     "{\"tool\":\"...\",\"args\":{...}}```. Não narre o que vai fazer: chame a ferramenta. "
                     "Não responda de memória o que uma tool confere (arquivo/sistema/data) — use a tool.")

# Famílias por substring no nome do modelo (litellm: 'openai/gpt-5.4', 'gemini-3-pro', 'zai/glm-5'…).
_FAMILY_RULES = (
    (("gpt", "codex", "grok", "o1", "o3", "o4"), _FAMILY_OPENAI),
    (("gemini", "gemma"), _FAMILY_GEMINI),
    (("qwen", "deepseek", "glm", "minimax", "mimo", "kimi", "moonshot"), _FAMILY_WEAK_OPEN),
)


def model_family_guidance(model: str) -> str:
    """Bloco curto específico da família do `model` (vazio p/ Claude/forte e desconhecidos — não infla)."""
    m = (model or "").lower()
    if not m:
        return ""
    for needles, block in _FAMILY_RULES:
        if any(n in m for n in needles):
            return block
    return ""


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
