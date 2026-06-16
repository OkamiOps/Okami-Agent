"""Uso de tokens + custo (porta enxuta do usage_pricing/insights do Hermes).

KEYSTONE: hoje os transports devolvem `str` cru e jogam fora o `usage` — que o SSE do codex JÁ entrega.
Aqui ficam (1) `CanonicalUsage` (buckets normalizados), (2) `Completion` (o resultado estruturado que
substitui o `str` e carrega texto + tool_calls + usage + finish_reason), (3) `normalize_usage` por
transport (com o pega-ratão: codex/OpenAI reportam total INCLUINDO cache → subtrair), e (4) custo com
modo **"incluído"** p/ assinatura (codex/claude são assinatura → mostra tokens, NUNCA inventa $).
Sem dependência de providers/transports → importável por qualquer um sem ciclo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


def _get(obj, key, default=0):
    """Lê de dict OU de objeto (litellm devolve um objeto usage com atributos)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        v = obj.get(key, default)
    else:
        v = getattr(obj, key, default)
    return v if v is not None else default


def _int(obj, key) -> int:
    try:
        return int(_get(obj, key, 0) or 0)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class CanonicalUsage:
    input_tokens: int = 0          # entrada NÃO-cacheada (já subtraído o cache)
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    requests: int = 0

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens

    def __add__(self, other: "CanonicalUsage") -> "CanonicalUsage":
        return CanonicalUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.reasoning_tokens + other.reasoning_tokens,
            self.requests + other.requests,
        )

    def to_dict(self) -> dict:
        return {"input": self.input_tokens, "output": self.output_tokens,
                "cache_read": self.cache_read_tokens, "cache_write": self.cache_write_tokens,
                "reasoning": self.reasoning_tokens, "requests": self.requests}

    @classmethod
    def from_dict(cls, d: dict | None) -> "CanonicalUsage":
        d = d or {}
        return cls(int(d.get("input", 0)), int(d.get("output", 0)), int(d.get("cache_read", 0)),
                   int(d.get("cache_write", 0)), int(d.get("reasoning", 0)), int(d.get("requests", 0)))


def normalize_usage(raw, *, transport: str) -> CanonicalUsage:
    """`raw` (dict ou objeto) do provider → buckets canônicos. None/vazio → zeros (1 request)."""
    if not raw:
        return CanonicalUsage(requests=1)
    if transport == "claude_cli" or "input_tokens" in _shapekeys(raw) and "cache_read_input_tokens" in _shapekeys(raw):
        # Anthropic: buckets JÁ separados (não subtrair).
        return CanonicalUsage(
            input_tokens=_int(raw, "input_tokens"),
            output_tokens=_int(raw, "output_tokens"),
            cache_read_tokens=_int(raw, "cache_read_input_tokens"),
            cache_write_tokens=_int(raw, "cache_creation_input_tokens"),
            requests=1,
        )
    if transport == "bedrock_native":                # Converse: inputTokens/outputTokens
        return CanonicalUsage(input_tokens=_int(raw, "inputTokens"), output_tokens=_int(raw, "outputTokens"),
                              requests=1)
    if transport == "gemini_native":                 # generateContent: usageMetadata.{prompt,candidates}TokenCount
        meta = _get(raw, "usageMetadata", {}) or raw
        return CanonicalUsage(input_tokens=_int(meta, "promptTokenCount"),
                              output_tokens=_int(meta, "candidatesTokenCount"), requests=1)
    if transport == "codex_oauth":
        total_in = _int(raw, "input_tokens")
        details = _get(raw, "input_tokens_details", {})
        cache_read = _int(details, "cached_tokens")
        cache_write = _int(details, "cache_creation_tokens")
        out_details = _get(raw, "output_tokens_details", {})
        return CanonicalUsage(
            input_tokens=max(0, total_in - cache_read - cache_write),   # total INCLUI cache → subtrair
            output_tokens=_int(raw, "output_tokens"),
            cache_read_tokens=cache_read, cache_write_tokens=cache_write,
            reasoning_tokens=_int(out_details, "reasoning_tokens"), requests=1,
        )
    # OpenAI Chat Completions / litellm / minimax
    prompt_total = _int(raw, "prompt_tokens")
    details = _get(raw, "prompt_tokens_details", {})
    cache_read = _int(details, "cached_tokens") or _int(raw, "cache_read_input_tokens")
    out_details = _get(raw, "completion_tokens_details", {}) or _get(raw, "output_tokens_details", {})
    return CanonicalUsage(
        input_tokens=max(0, prompt_total - cache_read),
        output_tokens=_int(raw, "completion_tokens"),
        cache_read_tokens=cache_read,
        reasoning_tokens=_int(out_details, "reasoning_tokens"), requests=1,
    )


def _shapekeys(raw) -> set:
    if isinstance(raw, dict):
        return set(raw.keys())
    return {k for k in ("input_tokens", "cache_read_input_tokens", "output_tokens") if hasattr(raw, k)}


@dataclass
class Completion:
    """Resultado estruturado de uma chamada ao modelo (substitui o `str` cru)."""
    text: str = ""
    tool_calls: list = field(default_factory=list)     # [{"id","name","arguments":str}] (Onda 3)
    usage: CanonicalUsage = field(default_factory=CanonicalUsage)
    finish_reason: str = "stop"                          # stop | tool_calls | length
    provider: str = ""                                   # quem REALMENTE respondeu (served-by §E5)
    model: str = ""


def as_completion(x) -> Completion:
    """Tolera o caminho legado/teste: str → Completion(text=str); Completion → ele mesmo."""
    if isinstance(x, Completion):
        return x
    if isinstance(x, str):
        return Completion(text=x, usage=CanonicalUsage(requests=1))
    if isinstance(x, tuple) and len(x) == 2:             # (text, usage_dict)
        return Completion(text=x[0] or "", usage=normalize_usage(x[1], transport="codex_oauth"))
    return Completion(text=str(x), usage=CanonicalUsage(requests=1))


# ----------------------------------------------------------------- custo
# Transports de ASSINATURA: mostra tokens, marca "incluído", NUNCA inventa $ (hard constraint do Okami).
_SUBSCRIPTION_TRANSPORTS = {"codex_oauth", "claude_cli"}

# Preço por 1M tokens (USD). Só p/ provider pay-per-token (minimax/openai-compat). Editável.
_PRICING: dict[tuple[str, str], dict] = {
    ("minimax", "MiniMax-M3"): {"input": Decimal("0.30"), "output": Decimal("1.20")},
    ("mimo", "mimo-v2.5-pro"): {"input": Decimal("0.20"), "output": Decimal("0.80")},
    ("anthropic", "claude-opus-4-8"): {"input": Decimal("5"), "output": Decimal("25"),
                                       "cache_read": Decimal("0.5"), "cache_write": Decimal("6.25")},
}


@dataclass(frozen=True)
class CostResult:
    amount_usd: Decimal | None
    status: str          # included | estimated | unknown
    label: str


def _bare(model: str) -> str:
    return model.split("/", 1)[1] if "/" in model else model


def estimate_cost(usage: CanonicalUsage, *, transport: str, provider: str, model: str) -> CostResult:
    if transport in _SUBSCRIPTION_TRANSPORTS:
        return CostResult(Decimal(0), "included", "incluído (assinatura)")
    entry = _PRICING.get((provider, _bare(model)))
    if not entry:
        return CostResult(None, "unknown", "—")
    amount = (Decimal(usage.input_tokens) * entry.get("input", Decimal(0))
              + Decimal(usage.output_tokens) * entry.get("output", Decimal(0))
              + Decimal(usage.cache_read_tokens) * entry.get("cache_read", Decimal(0))
              + Decimal(usage.cache_write_tokens) * entry.get("cache_write", Decimal(0))) / Decimal(1_000_000)
    return CostResult(amount, "estimated", f"~${amount:.4f}")


def summarize_store(store: dict) -> CanonicalUsage:
    """Soma o `usage` acumulado em todas as sessões do store (lifetime do agente)."""
    total = CanonicalUsage()
    for e in (store or {}).values():
        if isinstance(e, dict) and e.get("usage"):
            total = total + CanonicalUsage.from_dict(e["usage"])
    return total


def cache_hit_ratio(u: CanonicalUsage) -> float:
    """Quanto da entrada veio do cache (prova a economia do prompt caching)."""
    denom = u.input_tokens + u.cache_read_tokens
    return (u.cache_read_tokens / denom) if denom else 0.0


def format_tokens(n: int) -> str:
    """Compacto: 1234 → 1.2K, 3_400_000 → 3.4M."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    if n < 1_000_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    return f"{n / 1_000_000_000:.1f}B".replace(".0B", "B")
