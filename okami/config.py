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


def set_env_secret(name: str, value: str, *, path: str | None = None) -> Path:
    """Grava/atualiza `name=value` num .env — escrita ATÔMICA + 0600 (segredo só p/ o dono). Faz UPSERT
    (atualiza a linha se a chave já existir, senão acrescenta). Devolve o caminho escrito.

    path=None → .env GLOBAL ($OKAMI_HOME/.env). Fonte ÚNICA do segredo no disco — usada tanto pelo
    `okami config set` quanto pela tool store_secret (o agente recebe credencial e guarda AQUI)."""
    import os
    import tempfile
    p = Path(path) if path else global_env_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    out, done = [], False
    for ln in lines:
        # UPSERT tolerante a espaçamento: compara a CHAVE (lado esquerdo do 1º '=') já stripada, em vez de
        # startswith("KEY=") — 'KEY_A   =   old' não casava o prefixo e virava linha DUPLICADA.
        if "=" in ln and ln.split("=", 1)[0].strip() == name:
            out.append(f"{name}={value}")
            done = True
        else:
            out.append(ln)
    if not done:
        out.append(f"{name}={value}")
    data = "\n".join(out) + "\n"
    # tmp no mesmo diretório → os.replace é atômico (sem janela de arquivo meia-escrito/world-readable).
    fd, tmp = tempfile.mkstemp(dir=str(p.parent if str(p.parent) else "."), prefix=".env.", suffix=".tmp")
    try:
        try:
            os.fchmod(fd, 0o600)                       # 0600 ANTES de escrever o segredo
        except (AttributeError, OSError):              # Windows/sem suporte → segue
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, p)
        from okami.core.platform_compat import secure_chmod
        secure_chmod(p)                                # 0600 no POSIX (verifica) / ACL owner-only no Windows
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return p


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
    # Fontes de segredo plugáveis (item 19): DEPOIS do .env, não-destrutivo, fail-never-block. Com
    # Bitwarden Secrets Manager, só BWS_ACCESS_TOKEN fica em texto; o resto vem do cofre.
    try:
        from okami.core.secret_sources import apply_configured_sources
        res = apply_configured_sources()
        if res.get("error"):
            from okami import log
            log.warn(f"secret source: {res['error']} — seguindo com o .env.")
    except Exception:  # noqa: BLE001 — fonte de segredo NUNCA bloqueia o boot
        pass


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
    # Quirks DECLARATIVOS por provider (pesquisa #7 item 12) — opt-in, consumidos em providers._kwargs.
    # Default = comportamento de hoje. Cada provider tem manias diferentes; em vez de if-else espalhado,
    # o provider DECLARA o jeito que aceita e o _kwargs molda a chamada.
    # reasoning_style: como ESTE provider quer receber o esforço de raciocínio:
    #   "" / "reasoning_effort" → manda reasoning_effort (default — OpenAI/codex/litellm).
    #   "thinking"              → manda thinking={"type":"enabled","budget_tokens":N} (estilo Anthropic);
    #                             o reasoning_effort vira budget de tokens e é removido.
    #   "none"                  → não manda nenhum dos dois (modelo que recusa ambos / não-reasoning).
    reasoning_style: str = ""
    # vision_tool_messages: False remove blocos image_url de mensagens role=="tool" antes do envio —
    # alguns providers dão 400 com imagem dentro de resultado de tool (só aceitam vision em user/assistant).
    vision_tool_messages: bool = True
    # omit_temperature: True tira `temperature` do payload (de params E de override) — modelos de
    # reasoning (o-series/gpt-5) que SÓ aceitam o default e dão 400 se a temperature vier setada.
    omit_temperature: bool = False
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
    remote: dict[str, Any] = Field(default_factory=dict)     # {"hosts": {alias: {host,via,cwd}}, "ssh_agent": bool} (SSH/Tailscale)
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


def set_local(dotted_key: str, value):
    """Escreve uma chave DOTTED (ex.: 'remote.hosts.prod') no okami.local.yaml (overrides do usuário),
    merge não-destrutivo + escrita atômica. Usado por tools que persistem config a pedido do dono
    (ex.: remote_add). Devolve o caminho."""
    from okami.core.safe_io import read_yaml_resilient, secure_write_yaml
    p = config_dir() / "okami.local.yaml"
    raw = read_yaml_resilient(p, default={}) or {}
    if not isinstance(raw, dict):
        raw = {}
    parts = [k for k in str(dotted_key).split(".") if k]
    if not parts:
        raise ValueError("chave vazia.")
    node = raw
    for k in parts[:-1]:
        nxt = node.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            node[k] = nxt
        node = nxt
    node[parts[-1]] = value
    secure_write_yaml(p, raw)
    return p


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


def _resolve_secret(raw: dict, *keys: str) -> str:
    """Resolve um segredo de config: valor em TEXTO direto OU `<chave>_env` apontando p/ uma env-var
    (que o `_load_env`/secret_sources já injetou). Aceita hífen e underscore (host/app-password do YAML).
    Casa com o hard-constraint do Okami "secrets nunca em texto": o YAML pode só nomear a env-var."""
    for k in keys:
        for variant in (k, k.replace("_", "-")):
            if raw.get(variant):
                return str(raw[variant])
    for k in keys:
        for variant in (f"{k}_env", f"{k.replace('_', '-')}-env"):
            env_name = raw.get(variant)
            if env_name and os.getenv(str(env_name)):
                return str(os.getenv(str(env_name)))
    return ""


def _pick(raw: dict, *keys, default=None):
    """1º valor não-vazio entre `keys` (aceita hífen↔underscore). Vazio/ausente → default."""
    for k in keys:
        for variant in (k, k.replace("_", "-"), k.replace("-", "_")):
            v = raw.get(variant)
            if v not in (None, ""):
                return v
    return default


def parse_email_channel(raw: dict) -> dict:
    """Parseia channels.email (item 19) → kwargs do EmailChannel. NÃO instancia (o builders chama
    build_channel com isto). app-password resolve de texto OU env-var (secret_sources). Allowlist de
    remetentes DENY-BY-DEFAULT (e-mail é porta aberta). Host/port com default Gmail. Aditivo: dict
    vazio → user/app_password '' (o builders pula o canal por faltar credencial)."""
    raw = raw or {}
    user = str(_pick(raw, "user", default="") or "")
    app_password = _resolve_secret(raw, "app_password", "password")
    allow = _pick(raw, "allow", "allow_chats", "allow_senders", default=None)
    out = {
        "user": user,
        "app_password": app_password,
        "imap_host": str(_pick(raw, "imap_host", "host", default="imap.gmail.com")),
        "imap_port": int(_pick(raw, "imap_port", "port", default=993)),
        "smtp_host": str(_pick(raw, "smtp_host", default="smtp.gmail.com")),
        "smtp_port": int(_pick(raw, "smtp_port", default=465)),
        "mailbox": str(_pick(raw, "mailbox", default="INBOX")),
        "allow_chats": list(allow) if allow else None,
        "allow_all": bool(_pick(raw, "allow_all", default=False)),
    }
    pi = _pick(raw, "poll_interval", default=None)
    if pi is not None:
        out["poll_interval"] = float(pi)
    return out


def parse_webhook(raw: dict) -> dict:
    """Parseia gateway.webhook (item 14) → config normalizada do receptor HTTP. Cada ROTA tem um
    `secret` (resolvido de texto OU env-var). `deliver_only` DEFAULT True: a porta aberta só ENTREGA
    no chat (não roda o agente) sem opt-in explícito — postura segura p/ superfície exposta. Aditivo:
    dict vazio → bind localhost / sem rotas / deliver_only True."""
    raw = raw or {}
    routes_raw = raw.get("routes") or {}
    routes: dict[str, dict] = {}
    for name, rt in (routes_raw.items() if isinstance(routes_raw, dict) else []):
        rt = rt or {}
        routes[str(name)] = {"secret": _resolve_secret(rt, "secret")}
    return {
        "bind": str(_pick(raw, "bind", "host", default="127.0.0.1")),
        "port": int(_pick(raw, "port", default=8099)),
        "routes": routes,
        # default fail-SAFE: webhook não acorda o agente (só entrega) até o dono pôr deliver_only: false.
        "deliver_only": bool(_pick(raw, "deliver_only", default=True)),
    }


def build_config(raw: dict) -> OkamiConfig:
    """Constrói a OkamiConfig a partir de um dict já mesclado (global ou global+agente §10)."""
    providers: dict[str, ProviderConfig] = {}
    for name, pc in (raw.get("providers") or {}).items():
        data = dict(pc or {})
        data["name"] = name
        try:
            providers[name] = ProviderConfig(**data)
        except Exception as e:  # noqa: BLE001 — provider malformado NÃO derruba a config inteira: erro CLARO
            raise ValueError(f"provider '{name}' inválido em okami.yaml: {e}") from None

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
        remote=raw.get("remote") or {},          # SSH/Tailscale: hosts allowlist + ssh_agent (senão era dead-code)
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
