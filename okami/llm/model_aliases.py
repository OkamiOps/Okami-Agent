"""Resolvedor ÚNICO de provider/modelo (§ owner: "não consigo trocar fácil de provider ou de modelo").

Fonte única de verdade para `okami model`, `/model` (gateway) e `-p/-m` da CLI — os três chamam
`resolve(cfg, token)` em vez de reimplementar parsing. Sem isto, cada superfície tinha sua própria
lógica de "o que é provider vs modelo" e um typo passava batido (config-drop trap: silêncio > erro).

Formas de `token` aceitas:
  - alias semântico:      "sonnet", "opus", "haiku", "codex", "gpt", "minimax", "mimo", "grok"
  - alias de TIER (dinâmico, lido de cfg.providers — nunca hardcoded): "fast" (tier=local),
    "smart" (tier=strong)
  - id de provider puro:  "claude"          → mantém o modelo default do provider
  - provider/modelo:      "claude/sonnet-x" ou "claude sonnet-x" (validado contra pc.models)

Extensível via okami.yaml:
    model_aliases:
      barato: mimo
      melhor: claude/claude-opus-4-8
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from okami.config import OkamiConfig


class ModelAliasError(ValueError):
    """Alias/provider/modelo não resolvido — mensagem já pronta pra mostrar ao usuário (sem typo silencioso)."""


# alias semântico → (provider_id, model_hint). model_hint None = usa o `model` default do provider;
# uma string é tratada como PALAVRA-CHAVE buscada (substring, case-insensitive) em `pc.models` — assim
# não hardcoda a versão exata (claude-sonnet-4-6 hoje, outra amanhã): o catálogo do okami.yaml manda.
ALIASES: dict[str, tuple[str, str | None]] = {
    "claude": ("claude", None),
    "sonnet": ("claude", "sonnet"),
    "opus": ("claude", "opus"),
    "haiku": ("claude", "haiku"),
    "codex": ("codex", None),
    "gpt": ("codex", None),
    "minimax": ("minimax", None),
    "mimo": ("mimo", None),
    "grok": ("grok", None),
}

# alias de TIER → tier do ProviderConfig (§3.5). Resolvido em CIMA de cfg.providers, nunca aponta pra
# um id fixo — multi-vendor: o provider "fast"/"smart" muda conforme o que está configurado.
TIER_ALIASES: dict[str, str] = {
    "fast": "local",
    "smart": "strong",
}


def _parse_token(token: str) -> tuple[str, str | None]:
    """'<provider>/<modelo>' | '<provider> <modelo>' | '<provider>' → (provider, modelo|None)."""
    token = token.strip()
    if "/" in token:
        provider, _, model = token.partition("/")
        return provider.strip(), (model.strip() or None)
    if " " in token:
        provider, _, model = token.partition(" ")
        return provider.strip(), (model.strip() or None)
    return token, None


def _tier_provider(cfg: "OkamiConfig", tier: str) -> str | None:
    """1º provider com este tier — prioriza o default_provider atual, depois quem já está `ready`."""
    candidates = [pid for pid, pc in cfg.providers.items() if pc.tier == tier]
    if not candidates:
        return None
    if cfg.default_provider in candidates:
        return cfg.default_provider
    ready = [pid for pid in candidates if cfg.providers[pid].ready]
    return ready[0] if ready else candidates[0]


def _merged_alias_table(cfg: "OkamiConfig") -> dict[str, tuple[str, str | None]]:
    """ALIASES estático + `model_aliases:` do okami.yaml (extensível, sem editar código)."""
    table = dict(ALIASES)
    extra = getattr(cfg, "model_aliases", None) or {}
    for k, v in extra.items():
        table[str(k).strip().lower()] = _parse_token(str(v))
    return table


def _resolve_provider_model(cfg: "OkamiConfig", provider: str, model_hint: str | None,
                             *, alias: str | None) -> tuple[str, str | None]:
    if provider not in cfg.providers:
        disponiveis = ", ".join(cfg.providers) or "(nenhum)"
        origem = f" (alias '{alias}')" if alias else ""
        raise ModelAliasError(f"provider desconhecido: '{provider}'{origem} — disponíveis: {disponiveis}")
    pc = cfg.providers[provider]
    if model_hint is None:
        return provider, None
    if not pc.models:
        # sem catálogo (discovery ao vivo) → não dá p/ validar; passthrough de confiança (sem typo-detector).
        return provider, model_hint
    if model_hint in pc.models:
        return provider, model_hint
    matches = [m for m in pc.models if model_hint.lower() in m.lower()]
    if matches:
        return provider, matches[0]
    catalogo = ", ".join(pc.models)
    raise ModelAliasError(
        f"modelo '{model_hint}' não está no catálogo de '{provider}' — disponíveis: {catalogo}")


def resolve(cfg: "OkamiConfig", token: str) -> tuple[str, str | None]:
    """Resolve um token (alias | provider | provider/modelo) → (provider_id, modelo|None).

    Levanta ModelAliasError com mensagem pronta pra usuário se o token não bater com nada — NUNCA
    deixa um typo passar batido pro provider (Fase P0: "recall-junk"/"config-drop" ensinaram isso)."""
    if not token or not token.strip():
        raise ModelAliasError("token vazio — use um alias (sonnet/opus/codex/…), um provider, ou 'provider/modelo'.")
    token_norm = token.strip()
    key = token_norm.lower()

    if key in TIER_ALIASES:
        tier = TIER_ALIASES[key]
        pid = _tier_provider(cfg, tier)
        if not pid:
            raise ModelAliasError(f"nenhum provider com tier='{tier}' configurado (alias '{key}')")
        return pid, None

    table = _merged_alias_table(cfg)
    if key in table:
        provider, model_hint = table[key]
        return _resolve_provider_model(cfg, provider, model_hint, alias=key)

    provider, model_hint = _parse_token(token_norm)
    return _resolve_provider_model(cfg, provider, model_hint, alias=None)


def full_model_string(cfg: "OkamiConfig", provider_id: str, model: str | None) -> str:
    """Modelo BARU (id do catálogo, ex. 'claude-sonnet-4-6') → string completa no formato LiteLLM
    (ex. 'claude-subscription/claude-sonnet-4-6'), reaproveitando o PREFIXO já configurado em
    `providers.<id>.model` — sem isto, persistir o override quebrava o transport (perdia o prefixo)."""
    if not model:
        return ""
    if "/" in model:            # já veio qualificado (ex.: alguém passou o litellm string inteiro)
        return model
    pc = cfg.providers.get(provider_id)
    current = (pc.model if pc else "") or ""
    if "/" in current:
        prefix = current.rsplit("/", 1)[0]
        return f"{prefix}/{model}"
    return model


def effective(cfg: "OkamiConfig", *, flag: str | None = None,
              session_provider: str | None = None, session_model: str | None = None
              ) -> tuple[str, str | None]:
    """Precedência ÚNICA de provider/modelo (item (e) do design): -p/-m FLAG (token, resolvido por
    alias) > override de SESSÃO (/model já trocado nesta conversa) > okami.local.yaml > okami.yaml
    default. Os dois últimos já vêm mesclados em `cfg` (load_raw funde local sobre o yaml base) — não
    precisa reimplementar aqui. Testável isolado (sem precisar de uma Session/gateway de verdade)."""
    if flag:
        return resolve(cfg, flag)
    if session_provider:
        return session_provider, (session_model or None)
    return cfg.default_provider, None


def known_aliases(cfg: "OkamiConfig") -> list[tuple[str, str, str | None]]:
    """(alias, provider, model_hint) — p/ `okami model list` e telas de ajuda. Inclui tiers dinâmicos."""
    out: list[tuple[str, str, str | None]] = []
    for tier_alias, tier in TIER_ALIASES.items():
        pid = _tier_provider(cfg, tier)
        out.append((tier_alias, pid or "(nenhum)", None))
    for alias, (provider, model_hint) in _merged_alias_table(cfg).items():
        out.append((alias, provider, model_hint))
    return out
