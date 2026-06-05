"""Persona Compiler contextual (#8) — bloco CURTO de direção por turno. READ-ONLY.

NÃO injeta a identidade inteira (isso é `memory.files.core_block`: SOUL/VOICE/PERSONA continuam indo
ao prompt) e NÃO muda identidade (isso é `learning.persona`, com SOUL protegido + go/no-go). Aqui só
DESTILAMOS o DELTA do turno que o prompt estático não pega: quando um papo casual tem assunto TÉCNICO
(puxa p/ precisão) e o ESTADO EMOCIONAL da pessoa (muda a abertura, não a solução). Heurístico, sem LLM,
determinístico. Vazio quando não há sinal — não polui o prompt.
"""

from __future__ import annotations

import re
import unicodedata

_WORD = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", (s or "").lower()).encode("ascii", "ignore").decode("ascii")


# vocabulário técnico (folded) — se o ASSUNTO é isto, mesmo em papo, puxa p/ precisão.
_TECH = {"codigo", "code", "deploy", "bug", "erro", "error", "teste", "tests", "test", "api", "funcao",
         "function", "build", "git", "docker", "sql", "script", "refator", "lint", "compil", "servidor",
         "server", "endpoint", "componente", "component", "css", "html", "banco", "database", "query",
         "terminal", "shell", "commit", "merge", "branch", "regex", "json", "yaml", "bash", "python",
         "typescript", "javascript", "react", "schema", "stacktrace", "traceback", "exception", "kubernetes",
         "nginx", "ci", "pipeline", "token", "auth", "cache", "thread", "async", "lambda", "runtime"}

# estado da pessoa (needles já folded/sem acento) → ajusta a ABERTURA, não a solução.
_FRUST = ("nao funciona", "nao deu", "de novo", "ainda nao", "travou", "travad", "cansad", "que saco",
          "puta que", "pqp", "foda-se", "fodase", "nao aguento", "irritad", "nao to conseguindo",
          "to perdido", "que merda", "nao vai", "quebrou", "nao consigo", "ta dificil", "saco")
_EXCITE = ("adorei", "incrivel", "top demais", "que massa", "muito bom", "maravilh", "perfeito",
           "sensacional", "amei", "ficou foda", "que bom", "arrasou", "demais")
_URGENT = ("urgente", "rapido", "pra ontem", "preciso ja", "correndo", "sem tempo", "to com pressa",
           "ta na hora", "agora pra")


def _is_work(exit_criteria: list | None, contracts: dict | None) -> bool:
    """Modo TRABALHO = tem critério verificável de saída OU um contrato (o prompt já endurece sozinho)."""
    if contracts:
        return True
    return bool([c for c in (exit_criteria or []) if c.get("type") not in (None, "model_declared")])


def _has_tech(goal_folded: str) -> bool:
    toks = set(_WORD.findall(goal_folded))
    return bool(toks & _TECH) or any(k in goal_folded for k in ("refator", "compil", "deploy"))


def _emotion_line(goal_folded: str) -> str:
    if any(k in goal_folded for k in _FRUST):
        return "A pessoa parece travada/frustrada: reconheça o incômodo e destrave — sem minimizar nem dar sermão."
    if any(k in goal_folded for k in _URGENT):
        return "A pessoa está com pressa: vá direto ao que destrava agora; o detalhe vem depois."
    if any(k in goal_folded for k in _EXCITE):
        return "A pessoa está animada: acompanhe a energia, sem perder a precisão."
    return ""


def compile_turn(goal: str, exit_criteria: list | None = None, *, contracts: dict | None = None) -> str:
    """Bloco 'NESTE TURNO' (direção interna, read-only). DELTA contextual: registro técnico em papo +
    estado emocional. Devolve '' quando não há sinal — para não inflar o prompt."""
    g = _fold(goal)
    lines: list[str] = []
    # papo cujo ASSUNTO é técnico → puxa p/ precisão (o modo conversa é caloroso por padrão).
    if not _is_work(exit_criteria, contracts) and _has_tech(g):
        lines.append("Apesar de ser papo, o assunto é técnico: priorize precisão e objetividade, sem perder o tom.")
    emo = _emotion_line(g)
    if emo:
        lines.append(emo)
        lines.append("Isso muda a ABERTURA, não a solução — nunca troque o que é certo por agradar.")
    if not lines:
        return ""
    body = "\n".join(f"- {x}" for x in lines)
    return f"NESTE TURNO (direção interna — não recite nem comente isto):\n{body}"
