"""Tracker PROATIVO de rate-limit por headers — avisa ANTES de bater no 429.

A dor: o `rate_guard` é REATIVO — só age depois que o provider devolveu 429/529. Mas a maioria
dos providers (Anthropic, OpenAI…) já manda em CADA resposta quanto sobrou da quota nos headers
`x-ratelimit-remaining-{requests,tokens}`. Ler isso deixa a gente perceber "estou em 99% da cota
de requests, reset em 30s" e segurar/avisar ANTES de estourar — não depois.

Best-effort por princípio: header ausente, valor não-numérico, entrada None → nunca levanta,
no pior caso devolve dict vazio / None (a observação otimiza, jamais pode derrubar a chamada).
"""
from __future__ import annotations

# Os dois buckets que os providers reportam separadamente (cota de chamadas vs. de tokens).
_BUCKETS = ("requests", "tokens")
_FIELDS = ("limit", "remaining", "reset")


def parse_rate_headers(headers) -> dict:
    """Extrai os headers x-ratelimit-{limit,remaining,reset}-{requests,tokens} em buckets.

    Case-insensitive (provider varia entre `x-ratelimit-...` e `X-RateLimit-...`). `limit`/`remaining`
    viram float (são contagens); `reset` fica como veio (string tipo "30" ou "1m30s" — formato varia,
    não interpretamos aqui). Header ausente simplesmente não aparece no bucket. Devolve só os buckets
    que tiveram ALGUM campo presente: `{}` se nada de rate-limit veio.
    """
    out: dict[str, dict] = {}
    try:
        # normaliza chaves p/ lower uma vez — tolera dict-like de header (httpx/requests)
        low = {str(k).lower(): v for k, v in dict(headers or {}).items()}
    except (TypeError, ValueError, AttributeError):
        return out                                       # entrada não iterável como dict → best-effort
    for bucket in _BUCKETS:
        b: dict = {}
        for field in _FIELDS:
            raw = low.get(f"x-ratelimit-{field}-{bucket}")
            if raw is None:
                continue                                 # header ausente: ignora sem crashar
            if field == "reset":
                b[field] = raw                           # reset é opaco (formato varia por provider)
            else:
                try:
                    b[field] = float(raw)                # limit/remaining são números
                except (TypeError, ValueError):
                    pass                                  # valor zoado → ignora esse campo, não estoura
        if b:
            out[bucket] = b
    return out


def usage_warning(buckets, *, threshold: float = 0.8) -> str | None:
    """Aviso curto se ALGUM bucket passou de `threshold` de USO (1 - remaining/limit), senão None.

    Ex.: remaining=1/limit=100 → uso 99% → "⚠ quota de requests ~99% — reset em 30s". Pega o bucket
    de MAIOR uso (o mais perto do muro) p/ um aviso só. limit ausente/≤0 ou bucket incompleto → ignora
    (sem divisão por zero). Devolve None se nada cruzou o limiar — caller só repassa quando há string.
    """
    try:
        items = dict(buckets or {}).items()
    except (TypeError, ValueError, AttributeError):
        return None
    worst = None                                          # (uso, nome_bucket, reset)
    for name, data in items:
        try:
            limit = float(data.get("limit"))
            remaining = float(data.get("remaining"))
        except (TypeError, ValueError, AttributeError):
            continue                                      # bucket sem números utilizáveis
        if limit <= 0:
            continue                                       # sem teto conhecido → não dá p/ calcular uso
        used = 1.0 - max(0.0, remaining) / limit          # fração 0..1 (remaining negativo não vira uso <100%)
        if used >= threshold and (worst is None or used > worst[0]):
            worst = (used, name, data.get("reset"))
    if worst is None:
        return None
    used, name, reset = worst
    tail = f" — reset em {reset}s" if reset not in (None, "") else ""
    return f"⚠ quota de {name} ~{round(used * 100)}%{tail}"
