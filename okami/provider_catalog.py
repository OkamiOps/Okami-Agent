"""Catálogo de providers (§3.5) — presets prontos pra `okami provider add` / `okami setup`.

Cada preset sabe seu transport/auth/tier e QUAIS campos perguntar (api_base, model, chave). Chave nunca
vai pro okami.yaml (que é versionado): vira `api_key_env` + valor gravado no `.env`. Adicionar provider
fica em 3 cliques, sem editar YAML — e a lista é só estender aqui."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Field:
    key: str                 # chave no provider dict (ou "__secret__")
    q: str                   # pergunta
    default: str = ""
    kind: str = "text"       # text | secret
    env: str = ""            # p/ secret: nome da env var (vai pro .env, e api_key_env aponta pra ela)


@dataclass
class Preset:
    key: str                 # id sugerido do provider
    label: str
    hint: str
    base: dict = field(default_factory=dict)     # config estática do provider
    fields: list[Field] = field(default_factory=list)
    login: str = ""          # transport que exige `okami login` (codex_oauth/claude_cli/minimax_oauth)
    note: str = ""


# Ordenado por relevância p/ o usuário (assinaturas primeiro, depois locais e APIs comuns).
PRESETS: list[Preset] = [
    Preset("codex", "OpenAI Codex / ChatGPT", "assinatura (device flow, NÃO pay-as-you-go)",
           base={"model": "openai-codex/gpt-5.4", "auth": "oauth_subscription",
                 "transport": "codex_oauth", "tier": "strong", "context_window": 256000},
           login="codex_oauth", note="Login depois: okami login codex (habilite Device Code no ChatGPT)."),
    Preset("claude", "Anthropic Claude", "assinatura via CLI `claude` (NÃO pay-as-you-go)",
           base={"model": "claude-subscription/claude-opus-4-8", "auth": "oauth_subscription",
                 "transport": "claude_cli", "tier": "strong", "context_window": 200000},
           login="claude_cli", note="Usa o CLI oficial `claude` (instale e logue-o)."),
    Preset("lmstudio", "LM Studio (local)", "app desktop com servidor de modelo embutido",
           base={"auth": "api_key", "api_key": "lm-studio", "tier": "local", "context_window": 32768,
                 "capability": {"tool_mode": "json_constrained"}},
           fields=[Field("api_base", "API base", "http://localhost:1234/v1"),
                   Field("model", "Modelo carregado (openai/<id>)", "openai/qwen3.5-4b-mtp")]),
    Preset("ollama", "Ollama (local)", "modelos open self-hosted (OpenAI-compat)",
           base={"auth": "api_key", "api_key": "ollama", "tier": "local", "context_window": 32768,
                 "capability": {"tool_mode": "json_constrained"}},
           fields=[Field("api_base", "API base", "http://localhost:11434/v1"),
                   Field("model", "Modelo (openai/<nome>)", "openai/llama3.1")]),
    Preset("minimax", "MiniMax (OAuth Coding Plan)", "token plan (NÃO API key) — minimax.io",
           base={"model": "openai/MiniMax-M3", "api_base": "https://api.minimax.io/v1",
                 "transport": "minimax_oauth", "auth": "oauth_subscription", "tier": "weak",
                 "context_window": 1000000,
                 "oauth": {"client_id": "minimax-cli",
                           "device_authorization_url": "https://api.minimax.io/oauth/code",
                           "token_url": "https://api.minimax.io/oauth/token", "scope": ""}},
           login="minimax_oauth", note="Login depois: okami login minimax."),
    Preset("mimo", "Xiaomi MiMo", "MiMo-V2.5 — API key no .env",
           base={"api_base": "https://platform.xiaomimimo.com/v1", "auth": "api_key",
                 "tier": "weak", "context_window": 128000},
           fields=[Field("model", "Modelo", "openai/mimo-v2.5-pro"),
                   Field("__secret__", "API key da MiMo", env="MIMO_API_KEY", kind="secret")]),
    Preset("openai", "OpenAI API", "api.openai.com — API key",
           base={"api_base": "https://api.openai.com/v1", "auth": "api_key", "tier": "strong",
                 "context_window": 128000},
           fields=[Field("model", "Modelo", "openai/gpt-4o-mini"),
                   Field("__secret__", "API key", env="OPENAI_API_KEY", kind="secret")]),
    Preset("openrouter", "OpenRouter", "100+ modelos, pay-per-use",
           base={"api_base": "https://openrouter.ai/api/v1", "auth": "api_key", "tier": "strong",
                 "context_window": 128000},
           fields=[Field("model", "Modelo (openrouter/<id>)", "openrouter/auto"),
                   Field("__secret__", "API key", env="OPENROUTER_API_KEY", kind="secret")]),
    Preset("deepseek", "DeepSeek", "DeepSeek-V3 / R1 — API key",
           base={"api_base": "https://api.deepseek.com", "auth": "api_key", "tier": "strong",
                 "context_window": 64000},
           fields=[Field("model", "Modelo", "deepseek/deepseek-chat"),
                   Field("__secret__", "API key", env="DEEPSEEK_API_KEY", kind="secret")]),
    Preset("gemini", "Google Gemini", "modelos Gemini — API key",
           base={"auth": "api_key", "tier": "strong", "context_window": 1000000},
           fields=[Field("model", "Modelo", "gemini/gemini-1.5-flash"),
                   Field("__secret__", "API key", env="GEMINI_API_KEY", kind="secret")]),
    Preset("groq", "Groq", "inferência rápida (Llama/Mixtral) — API key",
           base={"api_base": "https://api.groq.com/openai/v1", "auth": "api_key", "tier": "weak",
                 "context_window": 128000},
           fields=[Field("model", "Modelo", "groq/llama-3.1-70b-versatile"),
                   Field("__secret__", "API key", env="GROQ_API_KEY", kind="secret")]),
    Preset("custom", "Endpoint custom (OpenAI-compat)", "qualquer /v1 — você informa base/model/chave",
           base={"auth": "api_key", "tier": "unknown"},
           fields=[Field("api_base", "API base (.../v1)", "http://localhost:8080/v1"),
                   Field("model", "Modelo (openai/<id>)", "openai/local-model"),
                   Field("__secret__", "API key (vazio = sem chave)", env="CUSTOM_API_KEY", kind="secret")]),
]


def preset(key: str) -> Preset | None:
    return next((p for p in PRESETS if p.key == key), None)


def menu_choices() -> list[tuple[str, str, str]]:
    """(key, label, hint) p/ o menu de seleção."""
    return [(p.key, p.label, p.hint) for p in PRESETS]
