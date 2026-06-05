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

# kinds que NÃO são reclassificados (já são específicos / vêm de outra fonte de verdade)
_SPECIFIC = {PREFERENCE, DECISION, SKILL, ERROR, TEMP,
             "summary", "turn", "procedural", "anti_pattern", "lesson"}

# Stems com âncora de boundary SÓ no início (\b...): "prefer" casa "prefere/preferência",
# "decid" casa "decidimos", "falh"→"falhou", etc. (trailing \b quebraria o stem matching).
_TEMP = re.compile(r"\b(?:por (?:agora|enquanto|ora)|provis[óo]ri|tempor[áa]ri|nesta sess[ãa]o|nesse chat|"
                   r"s[óo] (?:hoje|agora)|for now|temporar|just (?:for )?now|this session|"
                   r"esquec[ae]? depois|ignor[ae]? depois)", re.I)
_DECISION = re.compile(r"\b(?:decid|vamos (?:usar|adotar|seguir|fazer)|escolh|optei|defini|"
                       r"ficou (?:decidido|definido)|a decis[ãa]o|we (?:decided|chose|will use)|"
                       r"let.?s use|stick with|go with)", re.I)
_PREF = re.compile(r"\b(?:prefir|prefer|gosto de|gosta de|gostaria|sempre us|nunca us|n[ãa]o us|evite|"
                   r"me incomoda|odeio|i prefer|i like|always use|never use|don.?t use)", re.I)
_ERROR = re.compile(r"\b(?:erro|falh|bug|quebr|n[ãa]o funciona|exception|traceback|stack ?trace|deu ruim|"
                    r"fail|broke|does.?n.?t work|regress)", re.I)
_SKILL = re.compile(r"\b(?:passo a passo|passo \d|procedimento|como (?:fazer|configurar|rodar|usar|instalar)|"
                    r"receita|tutorial|how to|step.?by.?step|workflow)", re.I)


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
    if looks_secret(t):                              # P1: SEGREDO não vira memória de longo prazo —
        from okami import log                        # recusa (nem com force) p/ não vazar p/ sqlite/Honcho/holo
        log.warn("memory: recusei persistir conteúdo com cara de segredo (chave/token).")
        return None
    k = kind if kind in _SPECIFIC else classify(t, source)
    if not force and not should_persist(t, k):
        return None
    return MemoryItem(text=t, kind=k, source=source)
