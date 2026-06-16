"""Catálogo de capacidade POR MODELO (models.dev-lite, offline-first — paridade Hermes models_dev.py).

O Hermes consulta models.dev (4000+ modelos) p/ saber janela/vision/custo REAIS. Aqui é a versão
enxuta e honesta: um snapshot embutido dos modelos que aparecem nos nossos presets + os comuns, com
JANELA DE CONTEXTO e VISION. Conservador de propósito — entrada só com número confiável; modelo
desconhecido devolve None e o chamador cai no default por tier (comportamento antigo)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    context_window: int
    vision: bool = False
    # Níveis de reasoning_effort que ESTE modelo aceita, do menor p/ o maior (item 15a). Vazio = sem
    # tabela conhecida → clamp_effort passa direto (fail-open). Preenchido só p/ modelos onde mandar
    # um effort acima do teto dá 400 OU cobra reasoning que o modelo não usa direito (cost-safe).
    supported_efforts: tuple[str, ...] = ()
    audio: bool = False                 # #11: aceita áudio NATIVO de entrada (futuro STT-direto-ao-modelo)

    def supports_audio_input(self) -> bool:
        return self.audio


# Chave = nome NORMALIZADO (sem prefixo de provider, sem :tag, lowercase). O lookup casa por
# "começa com" da chave mais longa → "gpt-5.4-codex" cai em "gpt-5.4", "claude-opus-4-8" exato.
_SNAPSHOT: dict[str, ModelInfo] = {
    # OpenAI
    "gpt-5.5": ModelInfo(400_000, vision=True),
    "gpt-5.4": ModelInfo(400_000, vision=True),
    "gpt-5.3": ModelInfo(400_000, vision=True),
    "gpt-5": ModelInfo(400_000, vision=True),
    "gpt-4.1": ModelInfo(1_000_000, vision=True),
    "gpt-4o": ModelInfo(128_000, vision=True),
    "o3": ModelInfo(200_000, vision=True),
    "o4": ModelInfo(200_000, vision=True),
    # Anthropic
    "claude-opus-4": ModelInfo(200_000, vision=True),
    "claude-sonnet-4": ModelInfo(200_000, vision=True),
    "claude-haiku-4": ModelInfo(200_000, vision=True),
    "claude-fable-5": ModelInfo(200_000, vision=True),
    # Google
    "gemini-3": ModelInfo(1_000_000, vision=True),
    "gemini-2.5": ModelInfo(1_000_000, vision=True),
    "gemma": ModelInfo(128_000),
    # Abertos/API
    "deepseek": ModelInfo(128_000),
    "qwen3.5": ModelInfo(131_072),
    "qwen3": ModelInfo(131_072),
    "glm-5": ModelInfo(128_000),
    "glm-4": ModelInfo(128_000),
    "kimi-k2": ModelInfo(256_000),
    "grok-4": ModelInfo(256_000),
    "minimax": ModelInfo(1_000_000),
    "mistral-large": ModelInfo(128_000),
    "llama-3": ModelInfo(128_000),
    "llama-4": ModelInfo(256_000),
}
# Chaves mais longas primeiro → "gpt-4.1" ganha de "gpt-4", "qwen3.5" de "qwen3".
_KEYS = sorted(_SNAPSHOT, key=len, reverse=True)


def _normalize(model: str) -> str:
    m = (model or "").strip().lower()
    if "/" in m:                                   # "openai-codex/gpt-5.4" → "gpt-5.4"
        m = m.rsplit("/", 1)[-1]
    if ":" in m:                                   # ollama "qwen3.5:27b" → "qwen3.5"
        m = m.split(":", 1)[0]
    return m


def model_info(model: str) -> ModelInfo | None:
    """Capacidade conhecida do modelo (janela/vision), ou None se não estiver no snapshot."""
    m = _normalize(model)
    if not m:
        return None
    for key in _KEYS:
        if m.startswith(key):
            return _SNAPSHOT[key]
    return None


def model_vision(model: str) -> bool:
    """True só p/ modelo CONHECIDO como multimodal (fail-closed: desconhecido = False)."""
    info = model_info(model)
    return bool(info and info.vision)


# Ordem CANÔNICA dos níveis de reasoning_effort, do menor p/ o maior. clamp_effort usa isto p/
# comparar "<= pedido". Effort fora desta escala (provider exótico) → passa direto (fail-open).
_EFFORT_ORDER: tuple[str, ...] = ("minimal", "low", "medium", "high")

# Tabela de efforts SUPORTADOS por modelo (item 15a, cost-safe). Chave = nome NORMALIZADO (mesma
# regra do _SNAPSHOT: "começa com" da chave mais longa). Preenchido SÓ onde mandar um effort acima
# do teto dá 400 ou COBRA reasoning que o modelo não usa direito. Modelo ausente aqui → passa direto.
# Editável em runtime por testes/plugins (é um dict de módulo, não frozen).
_EFFORTS: dict[str, tuple[str, ...]] = {
    # família mini/spark: reasoning leve, sem o teto "high" do flagship (cobra caro à toa).
    "o4-mini": ("minimal", "low", "medium"),
    "o3-mini": ("minimal", "low", "medium"),
    "gpt-5.4-mini": ("minimal", "low", "medium"),
    "gpt-5.3-codex-spark": ("minimal", "low", "medium"),
    "gpt-5-mini": ("minimal", "low", "medium"),
}
_EFFORT_KEYS = sorted(_EFFORTS, key=len, reverse=True)


def supported_efforts(model: str) -> tuple[str, ...]:
    """Níveis de reasoning_effort que ESTE modelo aceita (menor→maior). Vazio = sem tabela conhecida
    (clamp passa direto). Consulta o _EFFORTS override primeiro, depois ModelInfo.supported_efforts."""
    m = _normalize(model)
    if not m:
        return ()
    for key in sorted(_EFFORTS, key=len, reverse=True):   # re-sort: testes injetam chaves em runtime
        if m.startswith(key):
            return _EFFORTS[key]
    info = model_info(model)
    return info.supported_efforts if info else ()


def clamp_effort(model: str, effort: str) -> str:
    """Rebaixa `effort` p/ o maior nível que o modelo suporta <= o pedido (cost-safe, item 15a).

    - Modelo desconhecido / sem tabela de efforts → passa direto (fail-open, comportamento antigo).
    - Effort vazio → vazio (sem reasoning declarado, nada a clampar).
    - Effort fora da escala canônica → passa direto (não inventamos rebaixamento p/ provider exótico).
    - Pedido abaixo de TODOS os suportados → menor suportado (nunca devolve vazio aqui)."""
    effort = (effort or "").strip().lower()       # item 31: "High"/" high " normalizam — senão escapavam crus
    if not effort:
        return effort
    sup = supported_efforts(model)
    if not sup or effort in sup:                  # sem tabela ou já é suportado → não mexe
        return effort
    if effort not in _EFFORT_ORDER:               # escala desconhecida → não sabemos rebaixar
        return effort
    want = _EFFORT_ORDER.index(effort)
    # maior suportado <= pedido (na ordem canônica); se nada <= pedido, cai no menor suportado.
    ranked = [s for s in sup if s in _EFFORT_ORDER]
    below = [s for s in ranked if _EFFORT_ORDER.index(s) <= want]
    if below:
        return max(below, key=lambda s: _EFFORT_ORDER.index(s))
    return min(ranked, key=lambda s: _EFFORT_ORDER.index(s)) if ranked else effort
