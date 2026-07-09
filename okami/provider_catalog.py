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
    model_prefix: str = ""   # prefixo LiteLLM dos modelos (ex.: "openai-codex/")
    models: list[str] = field(default_factory=list)  # modelos do plano (escolhível no add)
    login: str = ""          # transport que exige `okami login` (codex_oauth/claude_cli/minimax_oauth)
    note: str = ""


# Ordenado por relevância p/ o usuário (assinaturas primeiro, depois locais e APIs comuns).
PRESETS: list[Preset] = [
    # COST-SAFE (item 15c): o modelo BASE é o tier mais barato (mini), não o flagship. Sem uma escolha
    # explícita (auto-detecção pega `base` direto), um provider não deve cair no modelo mais caro à toa —
    # os flagships (gpt-5.5/gpt-5.4) seguem disponíveis em `models`, opt-in no momento do add.
    Preset("codex", "OpenAI Codex / ChatGPT", "assinatura (device flow, NÃO pay-as-you-go)",
           base={"model": "openai-codex/gpt-5.4-mini", "auth": "oauth_subscription",
                 "transport": "codex_oauth", "tier": "strong", "context_window": 256000},
           model_prefix="openai-codex/",
           models=["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex-spark"],
           login="codex_oauth", note="Login: okami login codex (device flow; habilite Device Code no ChatGPT)."),
    Preset("claude", "Anthropic Claude", "assinatura via CLI `claude` (NÃO pay-as-you-go)",
           base={"model": "claude-subscription/claude-opus-4-8", "auth": "oauth_subscription",
                 "transport": "claude_cli", "tier": "strong", "context_window": 200000},
           model_prefix="claude-subscription/",
           models=["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
           login="claude_cli", note="Usa o CLI oficial `claude` (instale e logue-o)."),
    # Locais/OpenAI-compat: o modelo é DESCOBERTO ao vivo via /models (Hermes). Só pedimos o api_base.
    Preset("lmstudio", "LM Studio (local)", "app desktop com servidor de modelo embutido",
           base={"auth": "api_key", "api_key": "lm-studio", "tier": "local", "context_window": 32768,
                 "native_tools": False, "capability": {"tool_mode": "json_constrained"}},
           model_prefix="openai/", fields=[Field("api_base", "API base", "http://localhost:1234/v1")]),
    Preset("ollama", "Ollama (local)", "modelos open self-hosted (OpenAI-compat)",
           base={"auth": "api_key", "api_key": "ollama", "tier": "local", "context_window": 32768,
                 "native_tools": False, "capability": {"tool_mode": "json_constrained"}},
           model_prefix="openai/", fields=[Field("api_base", "API base", "http://localhost:11434/v1")]),
    Preset("vllm", "vLLM (local/self-hosted)", "servidor OpenAI-compat de alta vazão",
           base={"auth": "api_key", "api_key": "vllm", "tier": "local", "context_window": 32768,
                 "native_tools": False, "capability": {"tool_mode": "json_constrained"}},
           model_prefix="openai/", fields=[Field("api_base", "API base", "http://localhost:8000/v1")]),
    Preset("llamacpp", "llama.cpp (local)", "servidor ./server do llama.cpp (OpenAI-compat)",
           base={"auth": "api_key", "api_key": "llama", "tier": "local", "context_window": 8192,
                 "native_tools": False, "capability": {"tool_mode": "json_constrained"}},
           model_prefix="openai/", fields=[Field("api_base", "API base", "http://localhost:8080/v1")]),
    Preset("minimax", "MiniMax (Token Plan)", "assinatura via Subscription Key — OpenAI-compat (minimax.io)",
           # native_tools=True EXPLÍCITO: MiniMax M-series suporta function-calling — sem isso o default None
           # cai num PROBE ao vivo (tool_choice=required, timeout 150s, veredito cacheado/instável por processo)
           # que podia derrubar o agente pro rail JSON-em-texto sozinho. Pinar mata o sorteio (achado da revisão).
           base={"model": "openai/MiniMax-M3", "api_base": "https://api.minimax.io/v1", "native_tools": True,
                 "auth": "api_key", "tier": "weak", "context_window": 1000000},
           model_prefix="openai/", models=["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.5", "MiniMax-M2.1"],
           fields=[Field("__secret__", "Subscription Key (Account ▸ Token Plan)", env="MINIMAX_API_KEY",
                         kind="secret")]),
    # DISCOVERABILITY (item 1): o transport `minimax_oauth` já existe (okami/llm/transports.py) e o
    # login genérico por device flow (okami/llm/oauth.py device_login) já sabe usá-lo — só faltava um
    # PRESET pra chegar lá por `okami provider add`. EXPERIMENTAL porque os endpoints OAuth da MiniMax
    # (client_id/device_authorization_url/token_url) não são publicados oficialmente — inferidos por
    # convenção RFC 8628 sobre o domínio api.minimax.io; confirme em platform.minimax.io/docs antes de
    # depender disso em produção (mesmo aviso que já existe em config.py `experimental`).
    # OAuth REAL da MiniMax (paridade Hermes hermes_cli/auth.py): client_id/URLs/scope confirmados; inferência
    # no endpoint /anthropic (protocolo Anthropic Messages, NÃO /v1 OpenAI-compat — era o erro do preset antigo).
    Preset("minimax-oauth", "MiniMax (assinatura via OAuth)",
           "login OAuth (SEM Subscription Key) — protocolo real do Hermes",
           base={"model": "MiniMax-M2.7", "api_base": "https://api.minimax.io/anthropic",
                 "native_tools": True, "auth": "oauth_subscription", "transport": "minimax_oauth",
                 "auth_flow": "minimax_oauth", "tier": "weak", "context_window": 1000000},
           model_prefix="anthropic/", models=["MiniMax-M2.7", "MiniMax-M3", "MiniMax-M2.5", "MiniMax-M2.1"],
           login="minimax-oauth",
           note="Login: okami login minimax-oauth (device flow OAuth). Inferência em /anthropic."),
    # DISCOVERABILITY (item 2): mesmo Token Plan da MiniMax, endpoint REGIONAL China (Hermes:
    # plugins/model-providers/minimax/__init__.py `minimax_cn`, base_url=https://api.minimaxi.com — nota
    # "minimaxi.com", não "minimax.io"). Chave própria (MINIMAX_CN_API_KEY) — contas/planos são distintos
    # entre as duas regiões, então não reaproveita MINIMAX_API_KEY.
    Preset("minimax-cn", "MiniMax China (Token Plan)",
           "mesmo Token Plan, endpoint regional China (api.minimaxi.com)",
           base={"model": "openai/MiniMax-M3", "api_base": "https://api.minimaxi.com/v1", "native_tools": True,
                 "auth": "api_key", "tier": "weak", "context_window": 1000000},
           model_prefix="openai/", models=["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.5", "MiniMax-M2.1"],
           fields=[Field("__secret__", "Subscription Key China (Account ▸ Token Plan)", env="MINIMAX_CN_API_KEY",
                         kind="secret")]),
    Preset("mimo", "Xiaomi MiMo (Token Plan)", "assinatura tp-xxxxx — OpenAI-compat regional",
           base={"api_base": "https://token-plan-ams.xiaomimimo.com/v1", "auth": "api_key",
                 "native_tools": True,              # idem minimax: cloud OpenAI-compat com function-calling → pina
                 "tier": "weak", "context_window": 128000},
           model_prefix="openai/", models=["mimo-v2.5-pro", "mimo-v2.5"],
           fields=[Field("__secret__", "API key 'tp-...' (Subscription Management)", env="MIMO_API_KEY",
                         kind="secret")]),
    Preset("openai", "OpenAI API", "api.openai.com — API key",
           base={"api_base": "https://api.openai.com/v1", "auth": "api_key", "tier": "strong",
                 "context_window": 128000},
           model_prefix="openai/", models=["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "o3-mini"],
           fields=[Field("__secret__", "API key", env="OPENAI_API_KEY", kind="secret")]),
    Preset("openrouter", "OpenRouter", "100+ modelos, pay-per-use",
           base={"api_base": "https://openrouter.ai/api/v1", "auth": "api_key", "tier": "strong",
                 "context_window": 128000},
           model_prefix="openrouter/",
           fields=[Field("__secret__", "API key", env="OPENROUTER_API_KEY", kind="secret")]),
    Preset("deepseek", "DeepSeek", "DeepSeek-V3 / R1 — API key",
           base={"api_base": "https://api.deepseek.com", "auth": "api_key", "tier": "strong",
                 "context_window": 64000},
           model_prefix="deepseek/", models=["deepseek-chat", "deepseek-reasoner"],
           fields=[Field("__secret__", "API key", env="DEEPSEEK_API_KEY", kind="secret")]),
    Preset("gemini", "Google Gemini", "modelos Gemini — API key",
           base={"auth": "api_key", "tier": "strong", "context_window": 1000000},
           model_prefix="gemini/",
           models=["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
           fields=[Field("__secret__", "API key", env="GEMINI_API_KEY", kind="secret")]),
    Preset("groq", "Groq", "inferência rápida (Llama/Mixtral) — API key",
           base={"api_base": "https://api.groq.com/openai/v1", "auth": "api_key", "tier": "weak",
                 "context_window": 128000},
           model_prefix="groq/",
           fields=[Field("__secret__", "API key", env="GROQ_API_KEY", kind="secret")]),
    Preset("xai", "xAI / Grok", "modelos Grok — API key (api.x.ai)",
           base={"api_base": "https://api.x.ai/v1", "auth": "api_key", "tier": "strong",
                 "context_window": 256000},
           model_prefix="xai/", models=["grok-4", "grok-4-fast", "grok-3", "grok-3-mini"],
           fields=[Field("__secret__", "API key", env="XAI_API_KEY", kind="secret")]),
    # DISCOVERABILITY (item 4): grok TEM assinatura OAuth (SuperGrok/Premium+) — Hermes confirma em
    # hermes_cli/auth.py: XAI_OAUTH_CLIENT_ID/XAI_OAUTH_DEVICE_CODE_URL são valores REAIS publicados no
    # próprio código do Hermes (não placeholder). O único ponto EXPERIMENTAL aqui é o token_url: a xAI usa
    # OIDC discovery (auth.x.ai/.well-known/openid-configuration) pra achar o token endpoint em runtime,
    # e o device_login genérico do Okami (okami/llm/oauth.py) só aceita uma URL estática — usamos a
    # convenção RFC 8628 sobre o mesmo issuer (auth.x.ai/oauth2/token); confirme via discovery antes de
    # depender em produção.
    # xAI OAuth REAL (paridade Hermes): token_url resolvido por OIDC discovery (auth.x.ai/.well-known/...),
    # não uma URL fixa — o fluxo okami/llm/oauth_xai.py cuida disso + rotação de refresh_token.
    Preset("xai-oauth", "xAI / Grok (assinatura SuperGrok)",
           "login OAuth (SuperGrok/Premium+), SEM API key — device flow + OIDC discovery",
           base={"model": "xai/grok-4", "api_base": "https://api.x.ai/v1", "auth": "oauth_subscription",
                 "transport": "minimax_oauth", "auth_flow": "xai_oauth",
                 "tier": "strong", "context_window": 256000},
           model_prefix="xai/", models=["grok-4", "grok-4-fast", "grok-3", "grok-3-mini"],
           login="xai-oauth",
           note="Login: okami login xai-oauth (device flow; abre auth.x.ai)."),
    # Anthropic Claude por ASSINATURA sem o CLI `claude` (PKCE paste-code, paridade Hermes) — destrava a
    # assinatura direto, com fallback pra ~/.claude e Keychain. Alternativa ao preset `claude` (que usa o CLI).
    Preset("claude-oauth", "Anthropic Claude (assinatura via OAuth)",
           "login OAuth PKCE (SEM o CLI `claude`) — cola o code, pronto",
           base={"model": "claude-subscription/claude-opus-4-8", "api_base": "https://api.anthropic.com",
                 "auth": "oauth_subscription", "transport": "minimax_oauth", "auth_flow": "anthropic_pkce",
                 "tier": "strong", "context_window": 200000},
           model_prefix="claude-subscription/",
           models=["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
           login="claude-oauth",
           note="Login: okami login claude-oauth (abre claude.ai, você cola o code#state)."),
    # Nous Research (assinatura) — device flow RFC 8628 (paridade Hermes).
    Preset("nous", "Nous Research (assinatura)", "login OAuth device flow (portal.nousresearch.com)",
           base={"model": "Hermes-4-405B", "api_base": "https://inference-api.nousresearch.com/v1",
                 "auth": "oauth_subscription", "transport": "minimax_oauth", "auth_flow": "nous_device",
                 "native_tools": True, "tier": "strong", "context_window": 128000},
           model_prefix="openai/", models=["Hermes-4-405B", "Hermes-4-70B"], login="nous",
           note="Login: okami login nous (device flow)."),
    # Qwen (Alibaba) por OAuth — sem login próprio aqui: loga pelo CLI `qwen`, o Okami lê/renova o arquivo dele.
    Preset("qwen-oauth", "Qwen (assinatura via CLI qwen)", "usa o login do CLI `qwen` (Okami lê/renova o token)",
           base={"model": "qwen-max", "api_base": "https://portal.qwen.ai/v1", "auth": "oauth_subscription",
                 "transport": "minimax_oauth", "auth_flow": "qwen_cli", "tier": "strong", "context_window": 256000},
           model_prefix="openai/", models=["qwen-max", "qwen-plus", "qwen-coder-plus"], login="qwen-oauth",
           note="Logue pelo CLI `qwen` uma vez; o Okami lê e renova ~/.qwen/oauth_creds.json sozinho."),
    # GitHub Copilot — device flow + exchange do token (paridade Hermes copilot_auth).
    Preset("copilot", "GitHub Copilot", "login OAuth device (usa sua assinatura Copilot)",
           base={"model": "gpt-4.1", "auth": "oauth_subscription", "transport": "minimax_oauth",
                 "auth_flow": "copilot_device", "tier": "strong", "context_window": 128000},
           model_prefix="openai/", models=["gpt-4.1", "claude-sonnet-4.5", "o4-mini"], login="copilot",
           note="Login: okami login copilot (device flow no github.com/login/device)."),
    Preset("mistral", "Mistral AI", "Mistral Large/Codestral — API key",
           base={"api_base": "https://api.mistral.ai/v1", "auth": "api_key", "tier": "strong",
                 "context_window": 128000},
           model_prefix="mistral/",
           models=["mistral-large-latest", "mistral-small-latest", "codestral-latest", "magistral-medium-latest"],
           fields=[Field("__secret__", "API key", env="MISTRAL_API_KEY", kind="secret")]),
    Preset("qwen", "Qwen (Alibaba DashScope)", "Qwen-Max/Coder via modo OpenAI-compat",
           base={"api_base": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "auth": "api_key",
                 "tier": "strong", "context_window": 256000},
           model_prefix="openai/", models=["qwen-max", "qwen-plus", "qwen3-coder-plus", "qwen3-max"],
           fields=[Field("__secret__", "API key (DashScope)", env="DASHSCOPE_API_KEY", kind="secret")]),
    Preset("zai", "Z.AI / GLM (Zhipu)", "GLM-4.6 / GLM-4.5 — API key",
           base={"api_base": "https://api.z.ai/api/paas/v4", "auth": "api_key", "tier": "strong",
                 "context_window": 200000},
           model_prefix="openai/", models=["glm-4.6", "glm-4.5", "glm-4.5-air"],
           fields=[Field("__secret__", "API key", env="ZAI_API_KEY", kind="secret")]),
    Preset("moonshot", "Kimi / Moonshot", "Kimi K2 — API key (api.moonshot.ai)",
           base={"api_base": "https://api.moonshot.ai/v1", "auth": "api_key", "tier": "strong",
                 "context_window": 256000},
           model_prefix="openai/", models=["kimi-k2-0905-preview", "moonshot-v1-128k"],
           fields=[Field("__secret__", "API key", env="MOONSHOT_API_KEY", kind="secret")]),
    Preset("nvidia", "NVIDIA NIM", "catálogo NIM (Llama/DeepSeek/…) — API key",
           base={"api_base": "https://integrate.api.nvidia.com/v1", "auth": "api_key", "tier": "strong",
                 "context_window": 128000},
           model_prefix="openai/", models=["meta/llama-3.3-70b-instruct", "deepseek-ai/deepseek-r1"],
           fields=[Field("__secret__", "API key", env="NVIDIA_API_KEY", kind="secret")]),
    Preset("cerebras", "Cerebras", "inferência ULTRA-rápida (Llama/Qwen) — API key",
           base={"api_base": "https://api.cerebras.ai/v1", "auth": "api_key", "tier": "weak",
                 "context_window": 128000},
           model_prefix="openai/", models=["llama-3.3-70b", "qwen-3-235b-a22b-instruct-2507"],
           fields=[Field("__secret__", "API key", env="CEREBRAS_API_KEY", kind="secret")]),
    Preset("fireworks", "Fireworks AI", "modelos open hospedados — API key",
           base={"api_base": "https://api.fireworks.ai/inference/v1", "auth": "api_key", "tier": "strong",
                 "context_window": 128000},
           model_prefix="openai/",
           models=["accounts/fireworks/models/llama-v3p3-70b-instruct", "accounts/fireworks/models/deepseek-v3"],
           fields=[Field("__secret__", "API key", env="FIREWORKS_API_KEY", kind="secret")]),
    Preset("together", "Together AI", "200+ modelos open — API key",
           base={"api_base": "https://api.together.xyz/v1", "auth": "api_key", "tier": "strong",
                 "context_window": 128000},
           model_prefix="together_ai/",
           models=["meta-llama/Llama-3.3-70B-Instruct-Turbo", "deepseek-ai/DeepSeek-V3"],
           fields=[Field("__secret__", "API key", env="TOGETHER_API_KEY", kind="secret")]),
    # item 3: rota "traga seu próprio provider" — qualquer vendor com token-plan/API key/endpoint
    # OpenAI-compat que não tem preset dedicado. Já persiste reusável: `_provider_add_flow` pergunta
    # "ID deste provider no okami.yaml" (default "custom") e grava normal em okami.yaml + a chave no
    # .env — dá pra adicionar VÁRIOS (ex.: "meu-token-plan", "empresa-x") só trocando o ID no prompt.
    # env aqui é só o default sugerido; troque o nome se for cadastrar mais de um custom.
    Preset("custom", "Traga seu provider (token-plan / API key / endpoint OpenAI-compat)",
           "qualquer /v1 que você já tenha — sem esperar preset dedicado; fica salvo no okami.yaml",
           base={"auth": "api_key", "tier": "unknown"}, model_prefix="openai/",
           fields=[Field("api_base", "API base (.../v1)", "http://localhost:8080/v1"),
                   Field("__secret__", "API key / token do plano (vazio = sem chave)", env="CUSTOM_API_KEY",
                         kind="secret")],
           note="Reusável: rode 'okami provider add' de novo pra cadastrar outro (dê um ID diferente)."),
]


def preset(key: str) -> Preset | None:
    return next((p for p in PRESETS if p.key == key), None)


def menu_choices() -> list[tuple[str, str, str]]:
    """(key, label, hint) p/ o menu de seleção."""
    return [(p.key, p.label, p.hint) for p in PRESETS]
