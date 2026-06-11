"""Background self-improvement review (estilo Hermes background_review.py) — MODEL-DRIVEN, não mecânico.

A diferença que conserta o "aprender lixo": o harness só CRONOMETRA a pergunta (a cada N turnos, só
em conclusão limpa); QUEM decide o que salvar é o MODELO, via as tools reais (remember/remember_user/
manage_skill), guiado por um prompt com a lista "Do NOT capture". Roda num fork ISOLADO de tools
(só escrita de memória/skill, auto-aprova esse conjunto seguro) e DEPOIS de a pessoa já ter a resposta.
O gate determinístico do memory.policy é a rede de segurança (barra lixo mesmo se o modelo escorregar).
"""

from __future__ import annotations

# tools que o review PODE usar (fork isolado): só escrita de memória/skill + terminais. Sem shell/spawn/
# arquivo → auto-aprovar é seguro.
REVIEW_TOOLS = {"remember", "remember_user", "recall_memory", "use_skill", "manage_skill",
                "respond", "task_complete", "task_blocked", "need_input"}

# A lista "Do NOT capture" é o ouro anti-lixo do Hermes (background_review.py:124-143). Vai no prompt
# (o modelo decide) E no gate determinístico do policy (backstop). Aqui no prompt, em PT.
_DO_NOT_CAPTURE = """NÃO capture (isto vira CONSTRAINT que te morde depois quando o ambiente muda):
- falha de AMBIENTE/setup: binário faltando, "command not found", credencial não configurada, pacote
  não instalado, erro de migração/caminho. A pessoa conserta — não é regra durável. (Se um conserto
  funcionou, capture o FIX — nunca "isso não funciona".)
- CLAIM NEGATIVO sobre uma tool/recurso SEU ("o browser não funciona", "X está quebrado"). Isso
  endurece em refusal que você cita contra si por meses, mesmo depois do problema resolvido.
- erro TRANSITÓRIO que se resolveu antes do fim da conversa. Se o retry funcionou, a lição é o retry.
- NARRATIVA de tarefa única ("analise esse PR", "resume o mercado hoje") — não é uma CLASSE de trabalho."""

_REVIEW_PROMPT = """Você está num REVIEW de auto-aprimoramento (rodando em background, depois que a
pessoa já recebeu a resposta). Olhe o turno abaixo e decida, com critério, se vale guardar algo DURÁVEL
e GENERALIZÁVEL. "Nada a salvar" é um resultado legítimo e comum — NÃO invente memória/skill.

SALVE (use a tool certa):
- MEMÓRIA sobre a PESSOA (`remember_user`): preferência, jeito de trabalhar, como gosta de ser tratada,
  decisão que ela tomou. É o que evita ela ter que repetir. Escreva como FATO DECLARATIVO, nunca como
  instrução a si mesmo: "prefere respostas curtas" ✓ — "responda sempre curto" ✗. Se o fato estará
  velho numa semana, NÃO é memória.
- MEMÓRIA do projeto/ambiente (`remember`): fato durável, convenção, decisão técnica, um FIX que vale.
- SKILL (`manage_skill`): SÓ se emergiu um PROCEDIMENTO reutilizável de uma CLASSE de tarefa (não a tarefa
  específica de hoje). Prefira EDITAR uma skill existente (action=edit) a criar uma nova. Nome no nível de
  CLASSE (kebab-case, ≤3 palavras) — nunca a frase do pedido / PR / erro / codinome.

FRUSTRAÇÃO DO USUÁRIO é sinal de SKILL de primeira classe (não só de memória): "para de fazer X",
"tá verboso demais", "você SEMPRE faz Y e eu odeio" → corrija a SKILL que governa aquela classe de
tarefa (a memória captura QUEM a pessoa é; a skill captura COMO fazer aquele tipo de trabalho p/ ela).
Correção de SEQUÊNCIA ("primeiro A, depois B") vira um Cuidado/passo na skill, não um fato solto.

{do_not}

Quando terminar (salvou ou não), chame task_complete com um resumo de 1 linha do que fez (ou "nada a
salvar"). NÃO faça mais nada além de memória/skill.

--- TURNO A REVISAR ---
{turn}
--- FIM ---"""


def build_review_goal(turn_context: str) -> str:
    return _REVIEW_PROMPT.format(do_not=_DO_NOT_CAPTURE, turn=turn_context.strip()[:6000])


def summarize_turn(task) -> str:
    """Compacta o turno p/ o review: pedido + sequência de tools (com efeito) + resultado. Sem dumps."""
    tools = " → ".join(s.tool for s in task.steps
                       if s.tool not in ("task_complete", "task_blocked", "need_input", "respond"))
    parts = [f"PEDIDO: {task.goal[:1500]}"]
    if tools:
        parts.append(f"AÇÕES: {tools}")
    if task.result:
        parts.append(f"RESPOSTA: {task.result[:1500]}")
    return "\n".join(parts)


def run_review(cfg, workspace, turn_context: str, *, skills_dir, model=None, provider=None,
               emit=lambda m: None) -> None:
    """Roda o review num fork de tools restrito (REVIEW_TOOLS), auto-aprovando esse conjunto seguro,
    SEM re-disparar aprendizado (learn=False → sem recursão). Best-effort: nunca derruba o turno."""
    from okami.runner import run_task
    try:
        run_task(cfg, workspace, build_review_goal(turn_context), provider=provider, model=model,
                 skills_dir=skills_dir, registry_filter=REVIEW_TOOLS,
                 approve=lambda req: True,           # conjunto de tools já é seguro (sem shell/arquivo/spawn)
                 learn=False, surface="review", emit=emit)
    except Exception as e:  # noqa: BLE001 — review é best-effort
        emit(f"(review falhou: {e})")
