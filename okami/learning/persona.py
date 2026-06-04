"""Persona evolutiva (§8) — VOICE/PERSONA aprendem com o tempo; SOUL é PROTEGIDO.

O usuário pediu identidade que EVOLUI ("se eu pedir pra mudar, ele tem que conseguir"), mas sem
DRIFT. Regras:
- **SOUL.md** (valores/essência) NUNCA auto-evolui — só muda a pedido explícito (`allow_soul=True`)
  e com aprovação. É a âncora contra deriva.
- **VOICE.md** (tom) e **PERSONA.md** (self-model) evoluem por FEEDBACK, sempre com **go/no-go**.
- Toda mudança é **versionada** (`.okami/persona_history.jsonl`) → **rollback** reverte arquivo+log.
- Edição é INCREMENTAL (bullet sob "## Evolução (aprendida)"), nunca reescrita — preserva a base.

Determinístico e testável; uma proposta por LLM (mais rica) entra por cima como `propose_llm`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_TARGETS = {"voice": "VOICE.md", "persona": "PERSONA.md", "soul": "SOUL.md"}
_EVO_HEADER = "## Evolução (aprendida)"
_HISTORY = ".okami/persona_history.jsonl"
_SIGNALS = ".okami/persona_signals.json"

# Feedback sobre CAPACIDADE/preferência/self → PERSONA; sobre TOM/estilo → VOICE (default).
_PERSONA_KEYS = ("prefiro", "priorize", "foque", "você é bom", "voce e bom", "seu forte",
                 "especialista", "seu papel", "se especializ", "você sabe", "voce sabe")


@dataclass
class PersonaEdit:
    target: str               # voice | persona | soul
    text: str                 # o bullet a adicionar (refinamento incremental)
    rationale: str = ""       # por quê (de onde veio o sinal)
    ts: str = ""              # data (injetada — testável; vazio = sem carimbo)
    section: str = ""         # subseção (Estilo|Evitar|Postura técnica|Self|Especialidade) — Hermes-style


def classify_target(feedback: str) -> str:
    """Heurística: capacidade/preferência → persona; tom/estilo → voice (default)."""
    low = feedback.lower()
    return "persona" if any(k in low for k in _PERSONA_KEYS) else "voice"


_AVOID_HINTS = ("evite", "evita", "nao ", "pare de", "para de", "menos ", "sem ", "chega de", "deixa de")


def _voice_section(text: str, target: str) -> str:
    """Seção do bullet (estilo Hermes: Identity/Style/Avoid/Technical)."""
    if target == "persona":
        return "Especialidade"
    low = _fold(text)
    if any(h in low for h in (_fold(x) for x in _AVOID_HINTS)):
        return "Evitar"
    if any(k in low for k in ("tecnic", "preciso", "objetiv", "registro")):
        return "Postura técnica"
    return "Estilo"


def propose(feedback: str, ts: str = "", target: str | None = None) -> PersonaEdit:
    """Proposta determinística a partir de um feedback do usuário."""
    tgt = target or classify_target(feedback)
    text = re.sub(r"\s+", " ", feedback).strip().rstrip(".")
    return PersonaEdit(target=tgt, text=text, rationale="feedback do usuário", ts=ts,
                       section=_voice_section(text, tgt))


def propose_llm(cfg, feedback: str, provider: str | None = None, ts: str = "") -> PersonaEdit:
    """Refina o feedback num bullet de identidade via LLM (constrained); cai p/ `propose` se falhar."""
    from okami.llm import providers as prov

    schema = {"type": "object",
              "properties": {"target": {"type": "string", "enum": ["voice", "persona"]},
                             "text": {"type": "string"},
                             "rationale": {"type": "string"}},
              "required": ["target", "text"]}
    sysmsg = ("Você refina a IDENTIDADE de um agente a partir de um feedback. Gere UM bullet curto, "
              "imperativo e durável (não um exemplo pontual). 'voice' = tom/estilo; 'persona' = "
              "capacidade/preferência/self. NUNCA mude valores essenciais (isso é o SOUL, fora de escopo).")
    msgs = [{"role": "system", "content": sysmsg},
            {"role": "user", "content": f"FEEDBACK: {feedback}\n\nGere o bullet."}]
    try:
        out = prov.complete_messages(cfg, msgs, provider=provider, response_schema=schema).strip()
        data = json.loads(out)
        tgt = data.get("target") if data.get("target") in ("voice", "persona") else classify_target(feedback)
        text = re.sub(r"\s+", " ", str(data.get("text") or feedback)).strip().rstrip(".")
        return PersonaEdit(target=tgt, text=text, rationale=str(data.get("rationale") or "feedback"), ts=ts)
    except Exception:  # noqa: BLE001 — LLM indisponível/ruído → heurística
        return propose(feedback, ts=ts)


# ----------------------------------------------------------------------- aplicar / versionar
def _evo_line(text: str, ts: str) -> str:
    return f"- ({ts}) {text}" if ts else f"- {text}"


def _append_evo(workspace, name: str, text: str, ts: str, header: str = _EVO_HEADER) -> None:
    p = Path(workspace) / name
    line = _evo_line(text, ts)
    if not p.exists():
        p.write_text(f"# {name[:-3]}\n\n{header}\n{line}\n", encoding="utf-8", newline="\n")
        return
    content = p.read_text(encoding="utf-8", errors="ignore")
    if line in content:                                  # dedup (independe de seção)
        return
    if header in content:                                # já existe a seção → insere logo após o cabeçalho
        content = content.replace(header, f"{header}\n{line}", 1)
        p.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")
        return
    p.write_text(content.rstrip() + f"\n\n{header}\n{line}\n", encoding="utf-8", newline="\n")


def record(workspace, edit: PersonaEdit) -> None:
    """Aplica o bullet na seção certa do arquivo-alvo e registra no changelog (para rollback)."""
    header = f"## {edit.section}" if edit.section else _EVO_HEADER
    _append_evo(workspace, _TARGETS[edit.target], edit.text, edit.ts, header)
    hp = Path(workspace) / _HISTORY
    hp.parent.mkdir(parents=True, exist_ok=True)
    rec = {"target": edit.target, "file": _TARGETS[edit.target], "text": edit.text,
           "rationale": edit.rationale, "ts": edit.ts}
    with hp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def is_safe_identity_text(text: str) -> bool:
    """Texto derivado da conversa vai pro system prompt (VOICE/PERSONA/USER) — escaneia ANTES de
    gravar (estilo Hermes, que escaneia o SOUL). Bloqueia prompt-injection/unicode oculto (HIGH+)."""
    from okami.skills.skill_security import Severity, scan_text
    return not any(f.severity >= Severity.HIGH for f in scan_text("identity", text))


def apply_evolution(workspace, edit: PersonaEdit, approve=None, allow_soul: bool = False) -> bool:
    """Evolui a identidade COM go/no-go. SOUL só com allow_soul (pedido explícito). Devolve aplicou?"""
    if edit.target not in _TARGETS:
        return False
    if edit.target == "soul" and not allow_soul:
        return False                                     # SOUL protegido: nunca auto-evolui
    if not is_safe_identity_text(edit.text):
        return False                                     # anti prompt-injection na identidade
    if approve is not None:
        req = {"tool": "evolve_persona", "reason": f"evoluir {_TARGETS[edit.target]}: {edit.text[:80]}",
               "category": "identity_file", "risk": "high" if edit.target == "soul" else "medium"}
        if not approve(req):
            return False
    record(workspace, edit)
    return True


def history(workspace) -> list[dict]:
    hp = Path(workspace) / _HISTORY
    if not hp.exists():
        return []
    return [json.loads(ln) for ln in hp.read_text(encoding="utf-8").splitlines() if ln.strip()]


def rollback(workspace, n: int = 1) -> list[dict]:
    """Reverte as últimas n evoluções: tira os bullets dos arquivos e do changelog."""
    items = history(workspace)
    if not items or n <= 0:
        return []
    removed = items[-n:]
    keep = items[: len(items) - len(removed)]
    hp = Path(workspace) / _HISTORY
    hp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in keep),
                  encoding="utf-8", newline="\n")
    for rec in reversed(removed):
        _remove_evo_line(workspace, rec["file"], rec["text"], rec.get("ts", ""))
    return removed


def _remove_evo_line(workspace, name: str, text: str, ts: str) -> None:
    p = Path(workspace) / name
    if not p.exists():
        return
    target = _evo_line(text, ts).strip()
    kept = [ln for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip() != target]
    p.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8", newline="\n")


# ===================================================================== OBSERVADOR (auto, gradual)
# O agente PERCEBE o estilo do usuário ao longo da conversa e evolui SOZINHO VOICE/PERSONA + USER.md
# — sem pedir aprovação a cada vez (pedido do usuário). É GRADUAL: um traço só "pega" depois de ser
# observado N vezes (anti-overfitting), e é REVERSÍVEL (changelog + /undo). SOUL nunca é tocado aqui.

@dataclass
class Signal:
    key: str                  # identidade do traço (acumula contagem)
    target: str               # voice | persona
    voice_text: str           # bullet de comportamento (vai pro VOICE/PERSONA)
    user_fact: str = ""       # fato sobre o usuário (vai pro USER.md)
    min_count: int = 2        # quantas observações até "pegar" (explícito=1, inferido=2+)
    section: str = "Estilo"   # subseção no arquivo (Estilo|Evitar|Postura técnica|Especialidade)


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()


# Palavrão PT-BR (sem acento, casado por limite de palavra). Inferido → gradual.
_PROFANITY = {"caralho", "porra", "puta", "puto", "putaquepariu", "pqp", "fdp", "merda", "cacete",
              "buceta", "foda", "fodase", "fodido", "fodida", "desgraca", "desgracado", "krl",
              "vsf", "viado", "corno", "arrombado", "bosta", "cu"}
_PROF_RE = re.compile(r"\b(" + "|".join(sorted(_PROFANITY, key=len, reverse=True)) + r")\b")
_NICK_RE = re.compile(r"\b(?:me chama de|pode me chamar de|me chame de)\s+([\wÀ-ÿ]{2,20})", re.IGNORECASE)
# Verbos de PREFERÊNCIA de estilo. NÃO inclui "responde/responda/escreve/escreva": esses são quase
# sempre COMANDO pontual ("responda apenas: oi"), não preferência durável — poluíam a VOICE. Um pedido
# de estilo de resposta ("responde mais curto") ainda casa via "mais"/"menos".
_STYLE_RE = re.compile(r"\b(seja|fala|fale|para de|pare de|menos|mais)\b", re.IGNORECASE)


def extract_signals(user_text: str) -> list[Signal]:
    """Heurística PT-BR: deduz traços de estilo da fala do usuário (palavrão, apelido, sarcasmo,
    registro técnico, e pedidos explícitos de estilo). A camada LLM (observe_llm) pega o resto."""
    out: list[Signal] = []
    low = _fold(user_text)

    if _PROF_RE.search(low):
        out.append(Signal("profanidade", "voice",
                          "Pode usar palavrões pontuais p/ ênfase/naturalidade, espelhando o registro do "
                          "usuário — nunca em conteúdo técnico crítico ou com terceiros formais.",
                          "Fala de forma crua e informal, usa palavrões (ex.: caralho, porra).",
                          min_count=2, section="Estilo"))

    m = _NICK_RE.search(user_text)
    if m:
        nick = m.group(1).strip()
        out.append(Signal(f"apelido:{_fold(nick)}", "voice",
                          f"Trate o usuário pelo apelido '{nick}'.",
                          f"Gosta de ser chamado de '{nick}'.", min_count=1, section="Estilo"))

    if "sarcas" in low or "ironi" in low:
        out.append(Signal("sarcasmo", "voice",
                          "Use humor sarcástico/irônico no registro casual; mantenha precisão no técnico.",
                          "Curte humor sarcástico/irônico.", min_count=1, section="Estilo"))

    if any(k in low for k in ("no tecnico", "tecnicamente", "seja preciso", "preciso de precisao",
                              "sem enrolacao", "objetivo", "direto ao ponto")):
        out.append(Signal("registro_tecnico", "voice",
                          "Registro adaptativo: solto/brincalhão no casual; preciso, enxuto e objetivo no técnico.",
                          "No técnico quer precisão e objetividade; no casual aceita informalidade.",
                          min_count=2, section="Postura técnica"))

    # Pedido EXPLÍCITO de estilo ("seja mais X", "para de Y") → comportamento direto (na hora).
    # Guarda: pula COMANDO pontual de conteúdo (tem ":"/aspas/"apenas"/demonstrativo) — senão a
    # tarefa do momento ("responda apenas: oi") virava "traço de estilo" permanente na VOICE.
    content_spec = (":" in user_text or '"' in user_text or "'" in user_text
                    or re.search(r"\b(apenas|somente|isso|isto|esse|essa|aquilo)\b", low) is not None)
    if _STYLE_RE.search(low) and len(user_text) <= 160 and not content_spec:
        directive = re.sub(r"\s+", " ", user_text).strip().rstrip(".")
        txt = directive[:1].upper() + directive[1:]
        out.append(Signal(f"estilo:{_fold(directive)[:40]}", "voice", txt, min_count=1,
                          section=_voice_section(txt, "voice")))
    return out


# --------------------------------------------------------- overlay de SESSÃO (estilo Hermes /personality)
# Persona TEMPORÁRIA só na sessão — NÃO grava em arquivo (≠ /feedback e ≠ observador, que aprendem).
PERSONA_PRESETS = {
    "conciso": "Seja extremamente conciso: respostas curtas, direto ao ponto, sem preâmbulo.",
    "tecnico": "Modo técnico: preciso, formal, com termos corretos; nada de gírias ou piadas.",
    "professor": "Modo professor: explique passo a passo, com analogias simples, paciente.",
    "casual": "Modo casual: tom leve e informal, como uma conversa entre amigos.",
    "direto": "Sem rodeios nem bajulação: vá direto ao que importa.",
    "pirata": "Responda como um pirata, com 'arrr' e gírias náuticas (mantendo o conteúdo correto).",
}


def overlay(preset_or_text: str) -> str:
    """Texto do overlay de sessão: um preset conhecido ou texto livre."""
    key = preset_or_text.strip().lower()
    body = PERSONA_PRESETS.get(key, preset_or_text.strip())
    return f"OVERLAY DE PERSONA (só nesta sessão, prevalece sobre o tom padrão): {body}" if body else ""


def _load_signals(workspace) -> dict:
    p = Path(workspace) / _SIGNALS
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_signals(workspace, store: dict) -> None:
    p = Path(workspace) / _SIGNALS
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(store, ensure_ascii=False, indent=0), encoding="utf-8", newline="\n")


def _accumulate(workspace, signals: list[Signal], *, ts: str = "", scale: int = 1,
                emit=lambda m: None) -> list[PersonaEdit]:
    """Acumula sinais e PROMOVE (auto, gradual) os que cruzaram o limiar → VOICE/PERSONA + USER.md.
    Compartilhado pela heurística (observe) e pela leitura por LLM (observe_llm)."""
    from okami.memory import files as memfiles

    if not signals:
        return []
    store = _load_signals(workspace)
    applied: list[PersonaEdit] = []
    for sig in signals:
        rec = store.setdefault(sig.key, {"count": 0, "committed": False})
        rec["count"] += 1
        if not rec["committed"] and rec["count"] >= max(1, sig.min_count * scale):
            edit = PersonaEdit(target=sig.target, text=sig.voice_text, section=sig.section,
                               rationale=f"observado {rec['count']}x", ts=ts)
            if apply_evolution(workspace, edit, approve=None):       # auto: sem aprovação (já escaneado)
                if sig.user_fact and is_safe_identity_text(sig.user_fact):
                    memfiles.append_user(workspace, sig.user_fact)   # USER.md também evolui (escaneado)
                rec["committed"] = True
                applied.append(edit)
                emit(sig.user_fact or sig.voice_text)
    _save_signals(workspace, store)
    return applied


def observe(workspace, user_text: str, *, ts: str = "", scale: int = 1,
            emit=lambda m: None) -> list[PersonaEdit]:
    """Observa UMA fala do usuário (heurística) e promove traços gradualmente. Ver `_accumulate`."""
    return _accumulate(workspace, extract_signals(user_text), ts=ts, scale=scale, emit=emit)


def observe_llm(cfg, workspace, conversation, *, provider: str | None = None, ts: str = "",
                scale: int = 1, emit=lambda m: None) -> list[PersonaEdit]:
    """Leitura RICA por LLM (constrained): pega sarcasmo pelo tom, nuances que a heurística não vê.
    Roda periodicamente (a cada N turnos no gateway). Os traços entram no MESMO acumulador gradual
    (min_count=2 → precisa o LLM apontar 2× p/ pegar, anti-alucinação). `conversation` = str ou
    lista de (papel, texto)."""
    from okami.llm import providers as prov

    convo = (conversation if isinstance(conversation, str)
             else "\n".join(f"{r}: {t}" for r, t in conversation[-20:]))
    schema = {"type": "object", "properties": {"traits": {"type": "array", "items": {
        "type": "object", "properties": {
            "key": {"type": "string"}, "target": {"type": "string", "enum": ["voice", "persona"]},
            "section": {"type": "string"}, "voice_text": {"type": "string"}, "user_fact": {"type": "string"}},
        "required": ["key", "target", "voice_text"]}}}, "required": ["traits"]}
    sysmsg = ("Observe o ESTILO e as PREFERÊNCIAS do usuário na conversa e proponha traços DURÁVEIS de "
              "identidade do agente. NÃO invente — só com evidência clara. 'voice'=tom/estilo, "
              "'persona'=capacidade/preferência. section: Estilo|Evitar|Postura técnica|Especialidade.")
    msgs = [{"role": "system", "content": sysmsg},
            {"role": "user", "content": f"CONVERSA:\n{convo}\n\nTraços observados:"}]
    try:
        out = prov.complete_messages(cfg, msgs, provider=provider, response_schema=schema).strip()
        traits = json.loads(out).get("traits", [])
    except Exception:  # noqa: BLE001 — LLM indisponível/ruído → não evolui agora
        return []
    signals: list[Signal] = []
    for tr in traits if isinstance(traits, list) else []:
        vt = re.sub(r"\s+", " ", str(tr.get("voice_text") or "")).strip()
        if not vt:
            continue
        tgt = tr.get("target") if tr.get("target") in ("voice", "persona") else "voice"
        sec = str(tr.get("section") or _voice_section(vt, tgt)) or "Estilo"
        signals.append(Signal(key=f"llm:{_fold(str(tr.get('key') or vt))[:40]}", target=tgt,
                              voice_text=vt, user_fact=str(tr.get("user_fact") or ""),
                              min_count=2, section=sec))     # LLM = gradual (anti-alucinação)
    return _accumulate(workspace, signals, ts=ts, scale=scale, emit=emit)
