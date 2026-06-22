"""Taste model de design (§9) — aprende o GOSTO do usuário e guia a geração.

A dor nº 1 do usuário com Hermes/OpenClaw: pedem ShadCN/HeroUI e recebem CSS genérico feio. Os
**gates** (§4.1) são a defesa DURA (proíbem hex inline, exigem `@/components/ui`, etc.). Este é o
crítico **SOFT**, complementar: a cada design produzido, o usuário reage **approved / rejected /
want_different**; viramos isso em **atratores** (estilos curtidos) e **repulsores** (rejeitados).
Na próxima geração, `steer()` injeta no prompt "prefira X, evite Y" e `score()` ranqueia candidatos:
  score = sim(atratores) − sim(repulsores)
"want_different" = repulsor LEVE do atual → explora longe do último, perto do que já agradou.

Representação leve e interpretável (sem servidor de embedding): design = TAGS (dimensões abaixo) +
descritor livre; vetor esparso (Counter) com cosine. Anti-overfitting: cap por lista + cold-start
que pede VARIEDADE quando ainda não há sinal.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_TASTE_FILE = ".okami/taste.json"
_MAX_ITEMS = 24                 # por lista (atratores/repulsores) — evita overfitting e crescimento sem fim
_W_ATTRACT, _W_REPEL = 1.0, 1.0
_TAG_W, _TOK_W = 2.0, 1.0        # tags pesam mais que tokens do descritor

# Dimensões sugeridas de gosto (guiam o agente/LLM a emitir tags consistentes).
TASTE_DIMENSIONS = [
    "library (shadcn|heroui|radix|tailwind|bootstrap|custom-css)",
    "palette (muted|vibrant|monochrome|pastel|neon|earthy|dark|light)",
    "density (airy|compact|balanced)", "radius (sharp|rounded|pill)",
    "shadow (flat|subtle|heavy)", "motion (none|subtle|playful)",
    "typography (sans|serif|mono|display)", "vibe (minimal|brutalist|corporate|editorial|fun)",
]


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", _fold(text)) if len(t) > 2]


def featurize(tags: list[str], descriptor: str = "") -> Counter:
    """Design → vetor esparso de TERMOS (namespace único → tags e descritor livre são comparáveis;
    tags só pesam mais). Assim feedback por texto livre casa com candidatos por tags."""
    f: Counter = Counter()
    for t in tags or []:
        for tok in (_tokens(t) or [_fold(t).strip()]):
            if tok:
                f[tok] += _TAG_W
    for tok in _tokens(descriptor):
        f[tok] += _TOK_W
    return f


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class Item:
    tags: list[str]
    descriptor: str = ""
    weight: float = 1.0
    label: str = ""

    def feat(self) -> Counter:
        return featurize(self.tags, self.descriptor)


@dataclass
class TasteProfile:
    attractors: list[Item] = field(default_factory=list)
    repulsors: list[Item] = field(default_factory=list)
    promoted: list[str] = field(default_factory=list)   # termos já promovidos p/ VOICE (§8) — não repetir

    # ------------------------------------------------------------------ feedback
    def record(self, verdict: str, tags: list[str], descriptor: str = "", label: str = "") -> None:
        """verdict: approved | rejected | want_different."""
        item = Item(tags=list(tags or []), descriptor=descriptor, label=label)
        feat = item.feat()
        if verdict == "approved":
            self.attractors.append(item)
            self._decay(self.repulsors, feat)          # mudou de ideia: enfraquece repulsor parecido
        elif verdict == "rejected":
            self.repulsors.append(item)
            self._decay(self.attractors, feat)
        elif verdict == "want_different":
            item.weight = 0.5                          # repulsão LEVE do atual → explorar
            self.repulsors.append(item)
        else:
            raise ValueError(f"verdict inválido: {verdict}")
        self._cap(self.attractors)
        self._cap(self.repulsors)

    @staticmethod
    def _decay(items: list[Item], feat: Counter, thresh: float = 0.6) -> None:
        for it in items:
            if cosine(feat, it.feat()) >= thresh:
                it.weight *= 0.5
        items[:] = [it for it in items if it.weight >= 0.2]   # some quando vira ruído

    @staticmethod
    def _cap(items: list[Item]) -> None:
        if len(items) > _MAX_ITEMS:                   # mantém os mais recentes/fortes
            items.sort(key=lambda it: it.weight)
            del items[: len(items) - _MAX_ITEMS]

    # ------------------------------------------------------------------ uso
    def score(self, tags: list[str], descriptor: str = "") -> float:
        """Pontua um candidato: perto dos atratores, longe dos repulsores."""
        feat = featurize(tags, descriptor)
        a = max((it.weight * cosine(feat, it.feat()) for it in self.attractors), default=0.0)
        r = max((it.weight * cosine(feat, it.feat()) for it in self.repulsors), default=0.0)
        return _W_ATTRACT * a - _W_REPEL * r

    def _top_terms(self, items: list[Item], k: int) -> list[str]:
        """Termos mais fortes (tags + tokens do descritor), ponderados pelo peso do item."""
        freq: Counter = Counter()
        for it in items:
            for term, w in it.feat().items():
                freq[term] += it.weight * w
        return [t for t, _ in freq.most_common(k) if t]

    def steer(self, k: int = 6) -> str:
        """Texto injetado no prompt de design (crítico soft)."""
        if not self.attractors and not self.repulsors:
            return ("GOSTO DE DESIGN: ainda aprendendo o seu gosto — explore VARIEDADE de estilos "
                    "(use o design system do contrato) e peça feedback (👍/👎).")
        like = self._top_terms(self.attractors, k)
        avoid = [t for t in self._top_terms(self.repulsors, k) if t not in like]   # gosto líquido
        parts = ["GOSTO DE DESIGN DO USUÁRIO (crítico soft — os gates do contrato continuam valendo):"]
        if like:
            parts.append("PREFIRA: " + ", ".join(like))
        if avoid:
            parts.append("EVITE: " + ", ".join(avoid))
        parts.append("Se o resultado lembrar o que foi EVITADO, refaça diferente.")
        return "\n".join(parts)

    # ------------------------------------------------------------------ persistência
    @staticmethod
    def _items(raw: list) -> list[Item]:
        return [Item(tags=d.get("tags", []), descriptor=d.get("descriptor", ""),
                     weight=float(d.get("weight", 1.0)), label=d.get("label", "")) for d in raw or []]

    @classmethod
    def load(cls, workspace) -> "TasteProfile":
        p = Path(workspace) / _TASTE_FILE
        if not p.exists():
            return cls()
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return cls(attractors=cls._items(d.get("attractors")), repulsors=cls._items(d.get("repulsors")),
                       promoted=list(d.get("promoted") or []))
        except (json.JSONDecodeError, OSError):
            return cls()

    def save(self, workspace) -> None:
        p = Path(workspace) / _TASTE_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        ser = lambda items: [{"tags": it.tags, "descriptor": it.descriptor, "weight": it.weight,  # noqa: E731
                              "label": it.label} for it in items]
        p.write_text(json.dumps({"attractors": ser(self.attractors), "repulsors": ser(self.repulsors),
                                 "promoted": self.promoted}, ensure_ascii=False),
                     encoding="utf-8", newline="\n")

    def promote_to_persona(self, workspace, min_count: int = 3) -> list[str]:
        """Liga taste→persona (§8↔§9): um termo curtido em ≥min_count designs vira preferência DURÁVEL
        no VOICE.md (auto, escaneado). Promove uma vez por termo (registrado em `promoted`)."""
        from okami.learning import persona

        freq: Counter = Counter()
        for it in self.attractors:
            for term in it.feat():                       # 1 voto por design aprovado que tem o termo
                freq[term] += 1
        done = []
        for term, cnt in freq.most_common():
            if cnt >= min_count and term not in self.promoted:
                edit = persona.PersonaEdit(target="voice", text=f"Em design, prefira '{term}'.",
                                           section="Estilo", rationale=f"gosto consistente ({cnt}x)")
                if persona.apply_evolution(workspace, edit, approve=None):
                    self.promoted.append(term)
                    done.append(term)
        return done


_VERDICTS = {"like": "approved", "approved": "approved", "dislike": "rejected", "rejected": "rejected",
             "different": "want_different", "want_different": "want_different"}


def record_feedback(workspace, verdict: str, descriptor: str, tags: list[str] | None = None,
                    promote: bool = True) -> TasteProfile:
    """Atalho: carrega, registra o feedback, PROMOVE gosto forte p/ VOICE (§8) e salva."""
    prof = TasteProfile.load(workspace)
    prof.record(_VERDICTS.get(verdict, verdict), tags or [], descriptor=descriptor)
    if promote:
        try:
            prof.promote_to_persona(workspace)           # taste→persona: termos consistentes viram VOICE
        except Exception:  # noqa: BLE001 — link p/ VOICE é OPCIONAL; nunca derruba o registro do feedback
            pass
    prof.save(workspace)
    return prof


def extract_tags_llm(cfg, descriptor: str, provider: str | None = None) -> list[str]:
    """Deriva TAGS estruturadas de um descritor livre via LLM (constrained, pelas dimensões §9).
    Cai p/ [] se o LLM falhar — o texto livre já casa por si (namespace único)."""
    from okami.llm import providers as prov

    schema = {"type": "object", "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
              "required": ["tags"]}
    sysmsg = ("Extraia 3-8 TAGS curtas de estilo de design do texto, pelas dimensões: "
              + "; ".join(TASTE_DIMENSIONS) + ". Responda só as tags (ex.: shadcn, muted, airy).")
    msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": descriptor}]
    try:
        out = prov.complete_messages(cfg, msgs, provider=provider, response_schema=schema).strip()
        tags = json.loads(out).get("tags", [])
        return [str(t).strip() for t in tags if str(t).strip()][:8]
    except Exception:  # noqa: BLE001
        return []
