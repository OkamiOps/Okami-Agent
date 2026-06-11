"""Carregamento de configuração do Okami (okami.yaml + .env).

Cada provider é descrito de forma agnóstica e resolvido via LiteLLM em runtime.
Foreshadowing do §3.5 (capability profile): o campo `tier` já distingue
strong/weak/local para, nas próximas fases, parametrizar o andaime adaptativo.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Segredos GLOBAIS do Okami: $OKAMI_HOME/.env (default ~/.okami/.env) — valem em QUALQUER workspace. É aqui que mora um
# token tipo ELEVENLABS_API_KEY/MIMO_API_KEY — configure uma vez, usa em todo lugar.
def global_env_path() -> Path:
    """Caminho do .env global ($OKAMI_HOME/.env, default ~/.okami/.env). Fonte única via okami.home."""
    from okami.home import env_path
    return env_path()


def _load_env() -> None:
    """Carrega segredos com precedência: ambiente real > .env do PROJETO (CWD) > .env GLOBAL ($OKAMI_HOME)
    > .env LEGADO (~/.okami, se OKAMI_HOME for custom). (load_dotenv não sobrescreve quem já existe.)"""
    load_dotenv()                                   # .env do projeto (CWD), se existir
    g = global_env_path()
    if g.exists():
        load_dotenv(g)                              # global preenche o que faltou (não sobrescreve)
    legacy = Path.home() / ".okami" / ".env"        # install antigo / OKAMI_HOME mudou → ainda honra
    if legacy != g and legacy.exists():
        load_dotenv(legacy)


# Carrega o quanto antes, para que api_key_env funcione já no import.
_load_env()

DEFAULT_CONFIG_NAMES = ("okami.yaml", "okami.yml")


class CapabilityProfile(BaseModel):
    """Andaime adaptativo por modelo (§3.5). Cresce nas próximas fases.

    tool_mode:
      - auto:             DERIVA da capacidade (tier) — default. weak/local → json_constrained;
                          strong → json_text; native_tools → native. Tira o footgun de o modelo
                          fraco ficar no json_text mudo (sem enforcement) e nunca chamar tool.
      - json_text:        ação como bloco ```json``` no texto (qualquer modelo).
      - json_constrained: força JSON válido via response_format json_schema (locais/fracos).
      - native:           tool-calling nativo do provider (forte). (parcial — futuro)
    """

    tool_mode: str = "auto"
    vision: bool = False        # modelo aceita imagem (vision §6) — só multimodais


class ProviderConfig(BaseModel):
    """Descrição de um provider de LLM.

    `model` é a string no formato LiteLLM, ex.:
      - "openai/gpt-5.4-codex"            (OpenAI / OpenAI-compat com api_base)
      - "anthropic/claude-opus-4-8"       (Anthropic)
      - "openai/qwen3.5-9b-mtp" + api_base (LMStudio local)
    """

    name: str
    model: str
    api_base: str | None = None
    api_key_env: str | None = None  # nome da env var que guarda a chave (aceita várias por vírgula)
    api_key: str | None = None      # chave literal (use só para dummy local)
    api_keys: list[str] = Field(default_factory=list)  # POOL de chaves (rotação/failover §3.5)
    auth: str = "api_key"           # api_key | oauth_subscription  (ver §16 / okami-provider-auth)
    transport: str = "litellm"      # litellm | claude_cli | codex_oauth | minimax_oauth
    oauth: dict[str, Any] | None = None     # device flow: client_id, device_authorization_url, token_url, scope
    login_cmd: list[str] | None = None      # CLI oficial p/ delegar login (ex.: codex login --device-auth)
    models: list[str] = Field(default_factory=list)  # ids alternativos disponíveis no plano
    tier: str = "unknown"           # strong | weak | local | unknown  (§3.5)
    # EXPERIMENTAL/opt-in: integração ainda não verificada de ponta a ponta (auth/endpoint em flux).
    # NÃO entra no failover automático nem é "pronta de verdade" no doctor — só vale se você escolher
    # explicitamente (okami provider default <id>). Evita que um 401/parse de provider em obras pareça
    # produto quebrado. Hoje: minimax (OAuth device — confirmar endpoints) e mimo (parse da API).
    experimental: bool = False
    fallback: list[str] = Field(default_factory=list)  # providers de backup se este falhar (§3.5 failover)
    context_window: int = 0         # janela do modelo em TOKENS (0 = default por tier) — §6.4
    chars_per_token: float = 4.0    # estimativa p/ converter tokens↔chars
    capability: CapabilityProfile = Field(default_factory=CapabilityProfile)
    params: dict[str, Any] = Field(default_factory=dict)
    # Esforço de raciocínio p/ modelos reasoning (gpt-5/codex, o-series, etc.): "minimal"|"low"|
    # "medium"|"high" (alguns aceitam mais). Vazio = default do modelo. Vai pro litellm
    # (reasoning_effort) e pro transport do codex (reasoning.effort). Trocável por sessão com /think.
    reasoning_effort: str = ""
    # Tool-calling NATIVO (Onda 3): o transport manda os schemas das tools e o modelo emite
    # function_call estruturado (não JSON-em-texto). EXPERIMENTAL, opt-in por provider — o codex
    # converte o function_call de volta p/ o protocolo de ação; off = comportamento atual intacto.
    native_tools: bool = False
    # tool_choice quando native_tools (OpenAI-compat): "auto" (modelo decide) | "required"/"any" (DEVE
    # chamar uma tool — como respond/task_complete SÃO tools, isto força ação sem deixar o modelo fraco
    # "só conversar"; substitui a função forçadora do json_constrained). Vazio = não envia (default do provider).
    tool_choice: str = ""
    notes: str | None = None

    def effective_tool_mode(self) -> str:
        """tool_mode REAL desta config: 'auto' deriva da capacidade (tier/native_tools). Explícito
        vence sempre — preset/usuário que fixou json_text/json_constrained não é re-derivado."""
        mode = (self.capability.tool_mode or "auto").strip().lower()
        if mode and mode != "auto":
            return mode
        if self.native_tools:                       # schemas nativos → o transport manda function-calling
            return "native"
        if self.tier in ("weak", "local"):          # fraco/local: força JSON válido (senão não chama tool)
            return "json_constrained"
        return "json_text"                          # strong/unknown: JSON-em-texto basta

    def resolved_key(self) -> str | None:
        keys = self.key_pool()
        return keys[0] if keys else None

    def key_pool(self) -> list[str]:
        """Pool de chaves (credential pool §3.5): `api_keys` + `api_key` + env (aceita vírgula).
        Rotaciona/failover entre elas em rate-limit → distribui carga e tolera 429."""
        pool = list(self.api_keys or [])
        if self.api_key:
            pool.append(self.api_key)
        if self.api_key_env:
            env = os.getenv(self.api_key_env) or ""
            pool.extend(k.strip() for k in env.split(",") if k.strip())
        seen, out = set(), []
        for k in pool:
            if k and k not in seen:
                seen.add(k)
                out.append(k)
        return out

    @property
    def ready(self) -> bool:
        """Pronto para uso, conforme o transport.

        - claude_cli: CLI 'claude' no PATH.
        - codex_oauth: ~/.codex/auth.json existe.
        - litellm: chave resolvida (local usa dummy).
        """
        from okami.home import read_path
        if self.transport == "claude_cli":
            return shutil.which("claude") is not None
        if self.transport == "codex_oauth":
            return (read_path("credentials", "codex.json").exists()
                    or (Path.home() / ".codex" / "auth.json").exists())
        if self.transport == "minimax_oauth":
            return read_path("credentials", f"{self.name}.json").exists()
        if self.auth == "oauth_subscription":
            return False
        return self.resolved_key() is not None


class OkamiConfig(BaseModel):
    default_provider: str
    providers: dict[str, ProviderConfig]
    contracts: dict[str, Any] = Field(default_factory=dict)  # ex.: {"ui": {...}}  (§4.1)
    memory: dict[str, Any] = Field(default_factory=dict)     # ex.: {"backend": "sqlite-fts5"}  (§6)
    approvals: dict[str, Any] = Field(default_factory=dict)  # {"mode": "manual", "always_allow": [...]} (§12)
    mcp: dict[str, Any] = Field(default_factory=dict)        # {"servers": {nome: {command, args, ...}}} (§12 MCP)
    agents: dict[str, Any] = Field(default_factory=dict)     # {"bindings": [...], "default": id} (§10 multi-agente)
    voice: dict[str, Any] = Field(default_factory=dict)      # {"stt": {...}, "tts": {...}}  (§13 voz)
    groups: list[Any] = Field(default_factory=list)          # salas multi-agente (§10 turn-taking)
    persona: dict[str, Any] = Field(default_factory=dict)    # {"observe": true, "gradual_scale": 1} (§8)
    gateway: dict[str, Any] = Field(default_factory=dict)    # {"auto_resume": false, "max_sessions": 500} (§13)
    learning: dict[str, Any] = Field(default_factory=dict)   # {"auto_skill": false} (§7 auto-aprimoramento)
    hooks: dict[str, Any] = Field(default_factory=dict)      # {evento: ["cmd"]} event hooks (§11)
    sandbox: dict[str, Any] = Field(default_factory=dict)    # {"backend": "local|docker", "mode": ...} (§P0 #2)
    tools: dict[str, Any] = Field(default_factory=dict)      # {"surfaces": {telegram: {deny:[...], allow:[...]}}} (P1.4)
    harness: dict[str, Any] = Field(default_factory=dict)    # {max_steps:200, max_stall_seconds:300} — passos/anti-travamento
    retention: dict[str, Any] = Field(default_factory=dict)  # poda/quota de disco p/ gateway long-running (ver maintenance.py)
    paperclip: dict[str, Any] = Field(default_factory=dict)  # {"require_evidence": true} — control plane exige prova p/ done
    auxiliary: dict[str, Any] = Field(default_factory=dict)  # modelo BARATO p/ fundo: {default|distill|review|moderator: {provider, model}}

    def provider(self, name: str | None = None) -> ProviderConfig:
        key = name or self.default_provider
        if key not in self.providers:
            disponiveis = ", ".join(self.providers) or "(nenhum)"
            raise KeyError(
                f"Provider '{key}' não encontrado em okami.yaml. Disponíveis: {disponiveis}"
            )
        return self.providers[key]


def find_config(start: Path | None = None) -> Path:
    start = start or Path.cwd()
    for d in [start, *start.parents]:
        for n in DEFAULT_CONFIG_NAMES:
            p = d / n
            if p.exists():
                return p
    # Fallback GLOBAL: a casa (~/.okami / $OKAMI_HOME). Sem isto, um install global só funcionava se você
    # rodasse de DENTRO do projeto — `okami chat` de qualquer outro diretório (caso do Windows) quebrava.
    from okami.home import okami_home
    for n in DEFAULT_CONFIG_NAMES:
        p = okami_home() / n
        if p.exists():
            return p
    raise FileNotFoundError(
        f"okami.yaml não encontrado (procurei em {start}, nos ancestrais, e em {okami_home()}). "
        "Rode `okami setup` (grava na casa global) ou crie um okami.yaml no projeto."
    )


def config_dir() -> Path:
    """Onde okami.yaml/okami.local.yaml moram p/ LER e ESCREVER: a pasta do projeto (okami.yaml no CWD/
    ancestral) se houver; senão a casa GLOBAL (~/.okami). É a fonte única dos comandos de config (setup/
    config set/unset/edit) — garante que um install global grava e lê na casa, de qualquer diretório."""
    try:
        return find_config().parent
    except FileNotFoundError:
        from okami.home import okami_home
        h = okami_home()
        h.mkdir(parents=True, exist_ok=True)
        return h


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_raw(path: Path | None = None) -> tuple[dict, Path]:
    """Lê o okami.yaml + merge do okami.local.yaml. Retorna (raw, caminho)."""
    from okami.core.safe_io import read_yaml_resilient
    cfg_path = path or find_config()
    raw = read_yaml_resilient(cfg_path, default={})          # recovery se a config base corromper (P1.2)
    for local_name in ("okami.local.yaml", "okami.local.yml"):
        local = cfg_path.parent / local_name
        if local.exists():
            raw = _deep_merge(raw, read_yaml_resilient(local, default={}))
            break
    return raw, cfg_path


def build_config(raw: dict) -> OkamiConfig:
    """Constrói a OkamiConfig a partir de um dict já mesclado (global ou global+agente §10)."""
    providers: dict[str, ProviderConfig] = {}
    for name, pc in (raw.get("providers") or {}).items():
        data = dict(pc or {})
        data["name"] = name
        providers[name] = ProviderConfig(**data)

    default_provider = raw.get("default_provider")
    if not default_provider:
        raise ValueError("config precisa de 'default_provider'.")
    if default_provider not in providers:
        raise ValueError(f"default_provider '{default_provider}' não está em providers.")

    return OkamiConfig(
        default_provider=default_provider,
        providers=providers,
        contracts=raw.get("contracts") or {},
        memory=raw.get("memory") or {},
        approvals=raw.get("approvals") or {},
        mcp=raw.get("mcp") or {},
        agents=raw.get("agents") or {},
        voice=raw.get("voice") or {},
        groups=raw.get("groups") or [],
        persona=raw.get("persona") or {},
        gateway=raw.get("gateway") or {},
        learning=raw.get("learning") or {},
        hooks=raw.get("hooks") or {},
        sandbox=raw.get("sandbox") or {},
        tools=raw.get("tools") or {},
        harness=raw.get("harness") or {},
        retention=raw.get("retention") or raw.get("cleanup") or {},
        paperclip=raw.get("paperclip") or {},
        auxiliary=raw.get("auxiliary") or {},
    )


def load_config(path: Path | None = None) -> OkamiConfig:
    raw, _ = load_raw(path)
    return build_config(raw)
