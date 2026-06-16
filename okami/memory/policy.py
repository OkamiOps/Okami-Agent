"""Política de escrita de memória (P2 #10 self-review) — nada entra sem CLASSIFICAÇÃO.

Antes, qualquer texto/resumo virava `kind="fact"` e era persistido sem critério. Aqui:
  • classify()      — rotula numa CATEGORIA: fact | preference | decision | skill | error | temp;
  • should_persist()— contexto EFÊMERO (temp) e trivial NÃO poluem a memória de longo prazo;
  • prepare()       — junta os dois e devolve um MemoryItem pronto (ou None = não persistir).

Heurística leve (sem custo de LLM), PT-BR + EN. Um `kind` ESPECÍFICO passado pelo chamador
(decision/skill/summary/…) é respeitado; só os genéricos (fact/vazio) são reclassificados.
"""

from __future__ import annotations

import re

from okami.memory.base import MemoryItem

# categorias canônicas
FACT, PREFERENCE, DECISION, SKILL, ERROR, TEMP = "fact", "preference", "decision", "skill", "error", "temp"

# DISCLOSURE de credencial em LINGUAGEM NATURAL ("minha senha é X", "password is Y", "PIN: 1234") — o
# looks_secret só pega token estruturado (sk-/ghp_/AKIA/Bearer). Aqui o over-bar é barato (memória), então
# basta keyword de credencial + atribuição (é/=/:/is) + valor ≥4. Menção SEM valor ("esqueci a senha") passa.
_NL_CREDENTIAL = re.compile(
    r"(?i)\b(?:senh[ao]|password|passwd|pass[\s-]?phrase|pin|credenci\w*|credential|secret[ao]?)\b"
    r"[^\n]{0,24}?(?:\b(?:é|eh|is|s[ãa]o)\b|[:=])\s*\S{4,}")

# kinds que NÃO são reclassificados (já são específicos / vêm de outra fonte de verdade)
_SPECIFIC = {PREFERENCE, DECISION, SKILL, ERROR, TEMP,
             "summary", "turn", "procedural", "anti_pattern", "lesson"}

# Stems com âncora de boundary SÓ no início (\b...): "prefer" casa "prefere/preferência",
# "decid" casa "decidimos", "falh"→"falhou", etc. (trailing \b quebraria o stem matching).
_TEMP = re.compile(r"\b(?:por (?:agora|enquanto|ora)|provis[óo]ri|tempor[áa]ri|nesta sess[ãa]o|nesse chat|"
                   r"s[óo] (?:hoje|agora)|for now|temporar|just (?:for )?now|this session|"
                   r"esquec[aei]? depois|ignor[ae]? depois)", re.I)  # esqueci/esquece/esqueça depois
_DECISION = re.compile(r"\b(?:decid|vamos (?:usar|adotar|seguir|fazer)|escolh|optei|defini|"
                       r"ficou (?:decidido|definido)|a decis[ãa]o|we (?:decided|chose|will use)|"
                       r"let.?s use|stick with|go with)", re.I)
_PREF = re.compile(r"\b(?:prefir|prefer|gosto de|gosta de|gostaria|sempre us|nunca us|n[ãa]o us|evite|"
                   r"me incomoda|odeio|i prefer|i like|always use|never use|don.?t use)", re.I)
_ERROR = re.compile(r"\b(?:erro|falh|bug|quebr|n[ãa]o funciona|exception|traceback|stack ?trace|deu ruim|"
                    r"fail|broke|does.?n.?t work|regress)", re.I)
_SKILL = re.compile(r"\b(?:passo a passo|passo \d|procedimento|como (?:fazer|configurar|rodar|usar|instalar)|"
                    r"receita|tutorial|how to|step.?by.?step|workflow)", re.I)

# "Do NOT capture" (Hermes background_review.py:124-143): conhecimento que VIRA constraint self-imposed
# e morde depois quando o ambiente muda. Bloqueado no caminho AUTOMÁTICO (agente/reflexão/review) — o
# usuário explícito (`force`) ainda salva. É o filtro DETERMINÍSTICO que protege mesmo com modelo fraco.
# (1) falha dependente de AMBIENTE/setup (o usuário conserta; não é regra durável):
_ENV_FAILURE = re.compile(
    r"\b(command not found|comando n[ãa]o encontrado|no such file|n[ãa]o existe o arquivo|"
    r"not installed|n[ãa]o (?:est[áa] )?instalad[oa]|modulenotfounderror|cannot find module|"
    r"missing (?:binary|dependency|depend[êe]ncia|module|m[óo]dulo|package|pacote)|"
    r"permission denied|permiss[ãa]o negada|unconfigured|n[ãa]o (?:est[áa] )?configurad[oa]|"
    r"missing credential|credential[^.\n]{0,20}not set)\b", re.I)
# (2) claim NEGATIVO sobre uma TOOL/recurso do agente ("X não funciona" → endurece em refusal que ele
# cita contra si mesmo por meses, mesmo depois do problema resolvido). Exige um sujeito-ferramenta perto.
_NEGATIVE_TOOL = re.compile(
    r"\b(?:tool|ferramenta|browser|navegador|playwright|docker|mcp|sandbox|run_shell|"
    r"recurso|feature|comando|command)\b[^.\n]{0,40}"
    r"(?:n[ãa]o funciona|doesn.?t work|don.?t work|is broken|(?:[ée]|est[áa]) quebrad|"
    r"n[ãa]o (?:consigo|d[áa] pra) usar|unavailable|indispon[íi]ve|not supported|n[ãa]o suporta)", re.I)


def do_not_capture(text: str) -> bool:
    """True se o texto cai na lista 'Do NOT capture' do Hermes (falha de ambiente OU claim negativo de
    tool). Usado p/ barrar auto-escrita de lixo que vira constraint — independe da qualidade do modelo."""
    t = text or ""
    return bool(_ENV_FAILURE.search(t) or _NEGATIVE_TOOL.search(t))


def classify(text: str, source: str = "") -> str:
    """Rotula o texto. Precedência: temp > decision > preference > error > skill > fact."""
    t = text or ""
    if _TEMP.search(t):
        return TEMP
    if _DECISION.search(t):
        return DECISION
    if _PREF.search(t):
        return PREFERENCE
    if _ERROR.search(t):
        return ERROR
    if _SKILL.search(t):
        return SKILL
    return FACT


def should_persist(text: str, kind: str) -> bool:
    """Memória de longo prazo: pula efêmero (temp) e trivial (curto demais)."""
    t = (text or "").strip()
    if len(t) < 8:
        return False
    return kind != TEMP


def prepare(text: str, source: str = "", kind: str | None = None, *, force: bool = False) -> MemoryItem | None:
    """Classifica + decide persistência → MemoryItem pronto (None = não persistir).

    `kind` específico é respeitado; genérico (fact/vazio) é reclassificado. `force` (ex.: usuário
    pedindo no CLI) ignora o gate de efêmero, mas ainda classifica a categoria certa."""
    t = (text or "").strip()
    if not t:
        return None
    from okami.core.redact import looks_secret
    if looks_secret(t) or _NL_CREDENTIAL.search(t):  # P1: SEGREDO não vira memória — token estruturado
        from okami import log                        # (looks_secret) OU disclosure de senha em linguagem natural
        log.warn("memory: recusei persistir conteúdo com cara de segredo (chave/token/senha).")
        return None
    if not force and do_not_capture(t):              # Do-NOT-capture: auto-escrita de falha-de-ambiente/
        from okami import log                        # claim-negativo NÃO vira memória (vira refusal depois)
        log.dbg("memory: descartei (Do-NOT-capture: falha de ambiente / claim negativo de tool).")
        return None
    k = kind if kind in _SPECIFIC else classify(t, source)
    if not force and not should_persist(t, k):
        return None
    return MemoryItem(text=t, kind=k, source=source)
