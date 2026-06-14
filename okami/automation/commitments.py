"""Compromissos INFERIDOS (item 10) — camada INVERTIDA estilo OpenClaw + entrega endurecida.

O scheduler (cron.json) captura compromissos EXPLÍCITOS ("me lembra amanhã") via regex
(`scheduler.infer_commitment`). Esta camada é o oposto: um modelo AUXILIAR lê os últimos turnos e
extrai follow-ups que NINGUÉM pediu em voz alta — o prazo que você mencionou de passagem, a consulta
que está chegando, o nó emocional que ficou em aberto. É o que dá à voz "confidente próximo" a
capacidade de voltar num assunto por conta própria, sem soar invasiva.

Três peças, todas com clock injetável e FAIL-OPEN (nunca travam o turno):
- `extract_commitments`: aux_complete(task="commitments") → candidatos, filtrados por um PISO de
  confiança POR kind (care_check_in é o mais alto: tocar num assunto pessoal sem ter certeza
  incomoda). Qualquer erro → [].
- `CommitmentStore`: persiste em .okami/commitments.json (SEPARADO de cron.json), com dedupe,
  carimbo de validade (~72h), teto diário de entregas e o ciclo pending→sent/dismissed/snoozed/expired.
- `safe_delivery_text`: o GUARD. A mensagem entregue É o `summary` autorado pelo modelo — NUNCA
  texto cru do turno. Se o summary cheira a turno replayado (rótulo de role, cerca de código,
  marcador de injeção), cai num check-in NEUTRO templado pelo kind. Vetor de injeção PERSISTIDA:
  load-bearing, não relaxe sem necessidade.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

# Catálogo FECHADO de kinds (qualquer coisa fora é descartada — o modelo não inventa categoria nova)
# e o piso de confiança de cada um. care_check_in mira no pessoal → exige MUITO mais certeza.
_FLOOR_DEFAULT = 0.72
_KIND_FLOOR = {
    "event_check_in": 0.72,   # "como foi a entrevista/consulta/viagem?"
    "deadline_check": 0.72,   # "o prazo de sexta saiu?"
    "care_check_in": 0.86,    # "como você está depois daquilo?" — piso ALTO de propósito
    "open_loop": 0.72,        # assunto/ideia que ficou pela metade
}
_KINDS = set(_KIND_FLOOR)

_EXPIRY_HOURS = 72            # compromisso inferido tem validade: ninguém quer um check-in de 2 semanas atrás
_DUE_CAP_DEFAULT = 3         # no máx. N entregas inferidas por dia (anti-spam)

_STORE_NAME = "commitments.json"

_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "commitments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "summary": {"type": "string"},
                    "confidence": {"type": "number"},
                    "due_in_hours": {"type": "number"},
                },
                "required": ["kind", "summary", "confidence"],
            },
        },
    },
    "required": ["commitments"],
}

_EXTRACT_PROMPT = (
    "Você lê os últimos turnos de uma conversa e detecta COMPROMISSOS IMPLÍCITOS — follow-ups que "
    "ninguém pediu explicitamente, mas que um amigo atento lembraria de retomar. Quatro tipos:\n"
    "- event_check_in: um evento futuro que vale perguntar depois ('como foi a entrevista?').\n"
    "- deadline_check: um prazo mencionado de passagem que vale conferir.\n"
    "- care_check_in: um assunto PESSOAL/emocional que ficou aberto (use só com MUITA certeza).\n"
    "- open_loop: uma ideia/decisão deixada pela metade que vale retomar.\n"
    "Regras: NÃO invente; se a pessoa já PEDIU um lembrete explícito, ignore (outro sistema cuida). "
    "Para cada um, escreva um `summary` curto e ACOLHEDOR, na SUA voz (não copie o texto do turno) — "
    "ele será a mensagem entregue. Dê `confidence` (0–1) e `due_in_hours` (quando retomar). "
    "Na dúvida, devolva menos. Responda só o JSON."
)


def _parse_aux_json(raw: str) -> dict:
    """Extrai o objeto JSON da resposta crua do aux (tolera texto em volta). {} em qualquer falha."""
    try:
        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        return json.loads(m.group(0)) if m else {}
    except (ValueError, AttributeError, TypeError):
        return {}


def extract_commitments(cfg, recent_turns: list[dict], now_ts: float) -> list[dict]:
    """Lê `recent_turns` (mensagens {role, content}) e devolve compromissos INFERIDOS que passam no
    piso de confiança do PRÓPRIO kind. FAIL-OPEN: qualquer erro (aux indisponível, JSON lixo, kind
    desconhecido) → [] — um turno do usuário NUNCA é bloqueado por causa desta camada de fundo."""
    convo = "\n".join(
        f"{(t.get('role') or 'user')}: {(t.get('content') or '')[:2000]}"
        for t in (recent_turns or []))
    msgs = [{"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user", "content": f"ÚLTIMOS TURNOS:\n{convo[:8000]}"}]
    from okami.llm.aux import aux_complete
    try:
        raw = aux_complete(cfg, "commitments", msgs, response_schema=_EXTRACT_SCHEMA, max_tokens=500)
    except Exception:  # noqa: BLE001 — fundo: aux indisponível → segue sem inferir (fail-open)
        return []
    data = _parse_aux_json(raw)
    out: list[dict] = []
    for item in (data.get("commitments") or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        if kind not in _KINDS:                            # fora do catálogo → descarta
            continue
        try:
            conf = float(item.get("confidence"))
        except (TypeError, ValueError):
            continue
        if conf < _KIND_FLOOR[kind]:                      # piso POR kind
            continue
        summary = str(item.get("summary") or "").strip()
        try:
            due_h = float(item.get("due_in_hours"))
        except (TypeError, ValueError):
            due_h = 24.0                                  # default acolhedor: volta no dia seguinte
        due_ts = now_ts + max(0.0, due_h) * 3600
        out.append({
            "kind": kind,
            "summary": summary,
            "confidence": conf,
            "due_ts": due_ts,
            "status": "pending",
            "dedupe_key": _dedupe_key(kind, summary),
        })
    return out


def _dedupe_key(kind: str, summary: str) -> str:
    """Chave de deduplicação: kind + resumo normalizado (case/espaços) — mesmo assunto não vira dois."""
    norm = re.sub(r"\s+", " ", (summary or "").strip().lower())
    return f"{kind}:{norm}"


# ------------------------------------------------------------------ guard de segurança (load-bearing)
# Sinais de que o `summary` é TURNO REPLAYADO e não texto autoral do modelo. Entregar isso de volta
# seria um vetor de injeção PERSISTIDA: o conteúdo do chat viraria uma mensagem nossa horas depois.
_REPLAY_SIGNALS = [
    re.compile(r"(?im)^\s*(system|user|assistant|tool|developer|role)\s*:", ),  # rótulo de role
    re.compile(r"```"),                                            # cerca de código
    re.compile(r"(?i)ignore (previous|all|above|prior) (instructions|prompts)"),
    re.compile(r"(?i)disregard (the|all|previous)"),
    re.compile(r"<<\s*sys\s*>>|\[/?inst\]|<\|.*?\|>"),             # marcadores de template/injeção
    re.compile(r"(?i)you are (now )?(a|an|the)\b"),                # tentativa de re-rolar a persona
]

# Check-in NEUTRO por kind — usado quando o summary é suspeito. Voz "confidente próximo", sem
# replayar NADA do turno: pergunta genérica e acolhedora que convida o usuário a contar.
_NEUTRAL_TEMPLATE = {
    "event_check_in": "Ei, lembrei de você agora. Como foi aquilo que você tinha pela frente?",
    "deadline_check": "Passando pra saber daquele prazo que você comentou — conseguiu fechar?",
    "care_check_in": "Tô aqui pensando em você. Como você está se sentindo com tudo aquilo?",
    "open_loop": "Ficou um assunto no ar da última vez. Quer retomar de onde a gente parou?",
}
_NEUTRAL_FALLBACK = "Ei, passando pra saber como você está. Tem algo que ficou no ar?"


def _looks_replayed(summary: str) -> bool:
    """True se o summary tem cara de texto cru do turno (não autoral) — então não entregamos ele."""
    s = summary or ""
    return any(rx.search(s) for rx in _REPLAY_SIGNALS)


def safe_delivery_text(c: dict) -> str:
    """O GUARD de entrega (stripLegacySourceText). A mensagem que vai pro usuário DEVE ser o `summary`
    autorado pelo modelo — NUNCA texto replayado do turno. Se o summary é vazio ou cheira a fonte
    replayada (rótulo de role, cerca de código, marcador de injeção), cai num check-in NEUTRO templado
    pelo kind. Load-bearing: é a barreira contra injeção PERSISTIDA via compromisso armazenado."""
    kind = str((c or {}).get("kind") or "").strip()
    summary = str((c or {}).get("summary") or "").strip()
    if not summary or _looks_replayed(summary):
        return _NEUTRAL_TEMPLATE.get(kind, _NEUTRAL_FALLBACK)
    return summary


class CommitmentStore:
    """Persiste compromissos inferidos em <root>/.okami/commitments.json (SEPARADO de cron.json).

    Dedupe na entrada, carimbo de validade (~72h), teto diário de entregas e o ciclo de status
    pending→sent/dismissed/snoozed/expired. Clock injetável p/ teste (mesma doutrina do Scheduler)."""

    def __init__(self, root: str = ".", *, clock=time.time):
        self.path = Path(root) / ".okami" / _STORE_NAME
        self._clock = clock

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []                                     # arquivo corrompido → começa limpo (fail-open)
        # JSON válido mas NÃO-lista (dict/int/str) também é "corrompido" p/ o store: due/add/expire
        # iterariam e estourariam AttributeError (item 33). Só dicts entram (lixo no array é descartado).
        return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []

    def save(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        os.replace(tmp, self.path)                        # gravação atômica

    def all(self) -> list[dict]:
        return self.load()

    def get(self, cid: str) -> dict | None:
        for c in self.load():
            if c.get("id") == cid:
                return c
        return None

    def add(self, c: dict) -> dict | None:
        """Adiciona um compromisso, SUPRIMINDO duplicado por dedupe_key. Carimba id + validade.
        Devolve o registro salvo, ou None se foi suprimido por já existir o mesmo assunto."""
        items = self.load()
        key = c.get("dedupe_key") or _dedupe_key(c.get("kind", ""), c.get("summary", ""))
        if any(x.get("dedupe_key") == key for x in items):
            return None                                   # mesmo assunto já registrado → suprime
        now = self._clock()
        rec = dict(c)
        rec["dedupe_key"] = key
        rec.setdefault("status", "pending")
        rec["id"] = self._new_id(items, c.get("kind", "c"))
        rec["created_ts"] = now
        rec["expires_ts"] = now + _EXPIRY_HOURS * 3600    # carimbo de validade (~72h)
        items.append(rec)
        self.save(items)
        return rec

    def _new_id(self, items: list[dict], kind: str) -> str:
        base = re.sub(r"[^a-z0-9_-]+", "-", str(kind).lower()) or "c"
        ids = {x.get("id") for x in items}
        i = 1
        while f"{base}-{i}" in ids:
            i += 1
        return f"{base}-{i}"

    def due(self, now_ts: float | None = None, cap: int = _DUE_CAP_DEFAULT) -> list[dict]:
        """Compromissos PENDENTES já vencidos (due_ts <= now), até `cap`/dia (anti-spam). Mais
        antigos primeiro — o que está esperando há mais tempo tem prioridade."""
        now = now_ts if now_ts is not None else self._clock()
        items = self.load()
        # cap é POR-DIA (item 18), não por-chamada: desconta o que JÁ foi entregue hoje. Senão um tick
        # a cada poucos minutos entregaria `cap` a cada tick → spam muito acima do prometido "/dia".
        day = int(now // 86400)
        sent_today = sum(1 for c in items if c.get("status") == "sent"
                         and int(float(c.get("sent_ts", 0)) // 86400) == day)
        remaining = max(0, cap - sent_today)
        ready = [c for c in items
                 if c.get("status") == "pending" and float(c.get("due_ts", 0)) <= now]
        ready.sort(key=lambda c: float(c.get("due_ts", 0)))
        return ready[:remaining]

    def mark(self, cid: str, status: str) -> bool:
        """Move o compromisso pelo ciclo: pending→sent/dismissed/snoozed/expired. False se id sumido."""
        items = self.load()
        hit = False
        for c in items:
            if c.get("id") == cid:
                c["status"] = status
                if status == "sent":
                    c["sent_ts"] = self._clock()      # carimba a entrega → cap POR-DIA (item 18)
                hit = True
        if hit:
            self.save(items)
        return hit

    def expire(self, now_ts: float | None = None) -> int:
        """Vira `expired` todo pending cuja validade passou. Devolve quantos expiraram — um check-in
        velho demais não tem mais graça (e não fica entupindo o due pra sempre)."""
        now = now_ts if now_ts is not None else self._clock()
        items = self.load()
        n = 0
        for c in items:
            if c.get("status") == "pending" and float(c.get("expires_ts", 0)) <= now:
                c["status"] = "expired"
                n += 1
        if n:
            self.save(items)
        return n
