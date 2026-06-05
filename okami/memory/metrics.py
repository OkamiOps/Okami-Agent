"""Métricas de memória (#13) — honestas sobre o que dá pra medir.

Duas famílias:
  • OBSERVÁVEIS — computadas direto do store, SEM rótulo: compactness, explainability, consolidação,
    confiança, e um `health_score` composto. São "termômetros" do estado da memória.
  • COM RÓTULO (`evaluate`) — precision@k / recall / MRR / scope_accuracy a partir de casos rotulados
    {query, relevant, scope}. É o harness de avaliação (#12/#13): precisão pesa MAIS que recall, e
    escopo errado é penalizado (regras do roadmap). Sem rótulo NÃO dá p/ inventar precision/recall.
Invariantes críticos (`integrity`): memória esquecida NÃO pode reaparecer (forget_success).
"""

from __future__ import annotations

import statistics


def summarize(stats: dict) -> dict:
    """Métricas observáveis derivadas dos agregados crus (store.stats())."""
    total_all = max(1, int(stats.get("total_all", 0)))
    active = int(stats.get("total_active", 0))
    superseded = total_all - active
    r = stats.get("retrievals", {}) or {}
    queries = max(1, int(r.get("queries", 0)))
    by_conf = stats.get("by_confidence", {}) or {}
    conf_total = max(1, sum(by_conf.values()))
    return {
        "context_compactness": round(int(r.get("count", 0)) / queries, 2),   # itens/consulta (menor = enxuto)
        "avg_retrieval_score": round(float(r.get("avg_score", 0.0)), 3),      # qualidade média do recall
        "retrieval_explainability_rate": 1.0,                                 # todo recall é logado (estrutural)
        "consolidation_rate": round(superseded / total_all, 3),              # fração já fundida/podada
        "low_confidence_rate": round(by_conf.get("low", 0) / conf_total, 3),
        "active_ratio": round(active / total_all, 3),
    }


def integrity(store) -> dict:
    """Invariantes: memória esquecida/arquivada/superseded NÃO aparece no conjunto ativo (forget_success).
    'memória esquecida reaparecendo é falha crítica' (roadmap)."""
    dump = store.export()
    active_ids = {i.id for i in store.recent(100_000)}
    inactive = [d for d in dump if d.get("status") in ("forgotten", "archived", "superseded") or d.get("superseded")]
    leaked = sum(1 for d in inactive if d["id"] in active_ids)
    forget_success = 1.0 if not inactive else round(1 - leaked / len(inactive), 3)
    return {"forget_success_rate": forget_success, "leaked_forgotten": leaked, "inactive_total": len(inactive)}


def health_score(stats: dict, integ: dict) -> float:
    """Score composto 0..1: integridade do forget (35%) + explainability (25%) + compactness saudável
    (20%) + pouca baixa-confiança (20%). Escopo/precisão entram via `evaluate` (precisam de rótulo)."""
    s = summarize(stats)
    compact = 1.0 if s["context_compactness"] <= 6 else max(0.0, 1 - (s["context_compactness"] - 6) / 10)
    return round(0.35 * integ.get("forget_success_rate", 1.0)
                 + 0.25 * s["retrieval_explainability_rate"]
                 + 0.20 * compact
                 + 0.20 * (1 - s["low_confidence_rate"]), 3)


def evaluate(store, cases: list[dict], k: int = 5) -> dict:
    """Eval COM ground-truth (#12/#13). Cada caso: {query, relevant:[textos] | relevant_ids:[ids], scope?}.
    precision@k = acertos/retornados · recall = acertos/relevantes · MRR · scope_accuracy (top-1).
    Precisão pesa mais que recall; escopo errado conta como falha."""
    all_items = store.recent(100_000)
    precs, recs, rrs, scope_hits, scope_n = [], [], [], 0, 0
    for case in cases:
        got = store.recall(case.get("query", ""), k)
        got_ids = [i.id for i in got]
        rel = set(case.get("relevant_ids") or [])
        for txt in case.get("relevant") or []:
            rel |= {i.id for i in all_items if txt.lower() in i.text.lower()}
        if rel:
            hits = [gid for gid in got_ids if gid in rel]
            precs.append(len(hits) / max(1, len(got_ids)))
            recs.append(len(hits) / len(rel))
            rr = next((1 / rank for rank, gid in enumerate(got_ids, 1) if gid in rel), 0.0)
            rrs.append(rr)
        if case.get("scope") and got:
            scope_n += 1
            scope_hits += 1 if (got[0].scope or "workspace") == case["scope"] else 0
    f1_w = None
    if precs and recs:
        p, r = statistics.mean(precs), statistics.mean(recs)
        f1_w = round((1.5 * p * r) / max(1e-9, 0.5 * p + r), 3)   # F-beta(β=0.5): precisão pesa 2× o recall
    return {
        "precision_at_k": round(statistics.mean(precs), 3) if precs else 0.0,
        "recall": round(statistics.mean(recs), 3) if recs else 0.0,
        "mrr": round(statistics.mean(rrs), 3) if rrs else 0.0,
        "scope_accuracy": round(scope_hits / scope_n, 3) if scope_n else None,
        "precision_weighted_f": f1_w,                              # combina, com precisão pesando mais
        "n_cases": len(cases),
    }


def report(store) -> dict:
    """Pacote completo p/ a CLI/teste: stats crus + observáveis + integridade + health."""
    st = store.stats()
    integ = integrity(store)
    return {"stats": st, "observed": summarize(st), "integrity": integ,
            "health_score": health_score(st, integ)}
