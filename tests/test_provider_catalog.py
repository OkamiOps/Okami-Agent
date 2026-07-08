"""Catálogo de providers (§3.5): presets bem-formados + cobertura estilo Hermes/OpenClaw."""

from __future__ import annotations

from okami.config import build_config
from okami.provider_catalog import PRESETS, menu_choices, preset


def _build_one(provider_id: str, base: dict):
    """build_config REAL (não SimpleNamespace — memória okami-config-drop-trap): garante que todo
    campo do preset.base tem correspondente em ProviderConfig, senão o campo morre silencioso."""
    raw = {"default_provider": provider_id, "providers": {provider_id: dict(base)}}
    return build_config(raw)


def test_keys_unique():
    keys = [p.key for p in PRESETS]
    assert len(keys) == len(set(keys))


def test_every_preset_is_well_formed():
    for p in PRESETS:
        assert p.key and p.label and p.model_prefix, p.key
        for f in p.fields:
            if f.kind == "secret":
                assert f.env, f"{p.key}: campo secret sem env var"   # segredo → .env, nunca YAML


def test_subscription_providers_use_oauth_or_cli():
    # restrição dura: codex/claude SEMPRE assinatura via OAuth/CLI — NUNCA pay-as-you-go (ToS).
    for key in ("codex", "claude"):
        p = preset(key)
        assert p.base.get("auth") == "oauth_subscription" and p.login, key


def test_minimax_uses_token_plan_subscription_key_not_payg():
    # MiniMax Token Plan (assinatura) = Subscription Key em Bearer (OpenAI-compat), conforme a doc oficial.
    # NÃO é pay-as-you-go: a chave vem do Token Plan e mora SÓ no .env (MINIMAX_API_KEY).
    p = preset("minimax")
    assert p.base.get("auth") == "api_key"
    secrets = [f for f in p.fields if f.kind == "secret"]
    assert secrets and secrets[0].env == "MINIMAX_API_KEY"
    assert "subscription" in p.hint.lower() or "token plan" in (secrets[0].q or "").lower()


def test_catalog_has_broad_coverage():
    keys = {p.key for p in PRESETS}
    # locais
    assert {"lmstudio", "ollama", "vllm", "llamacpp"} <= keys
    # APIs comuns (estilo Hermes/OpenClaw)
    assert {"openai", "openrouter", "deepseek", "gemini", "groq", "xai", "mistral",
            "qwen", "zai", "moonshot", "nvidia", "cerebras", "fireworks", "together"} <= keys
    assert len(PRESETS) >= 20


def test_api_presets_have_https_base():
    for p in PRESETS:
        base = p.base.get("api_base", "")
        if p.base.get("auth") == "api_key" and base and "localhost" not in base:
            assert base.startswith("https://"), f"{p.key}: API remota deve ser https"


def test_menu_choices_matches_presets():
    assert len(menu_choices()) == len(PRESETS)
    assert all(len(c) == 3 for c in menu_choices())          # (key, label, hint)


# --- item 1: discoverability — minimax subscription (OAuth) --------------------------------------


def test_minimax_oauth_preset_is_pickable():
    p = preset("minimax-oauth")
    assert p is not None
    assert ("minimax-oauth", p.label, p.hint) in menu_choices()


def test_minimax_oauth_preset_wires_oauth_transport_and_login():
    p = preset("minimax-oauth")
    assert p.base.get("transport") == "minimax_oauth"
    assert p.base.get("auth") == "oauth_subscription"
    assert p.login == "minimax_oauth"
    oauth = p.base.get("oauth") or {}
    assert oauth.get("device_authorization_url") and oauth.get("token_url")


def test_minimax_oauth_builds_valid_provider_config():
    p = preset("minimax-oauth")
    cfg = _build_one("minimax-oauth", p.base)
    pc = cfg.providers["minimax-oauth"]
    assert pc.transport == "minimax_oauth"
    assert pc.auth == "oauth_subscription"
    assert pc.oauth and pc.oauth["device_authorization_url"]
    assert pc.experimental is True                    # endpoints não confirmados oficialmente


# --- item 2: minimax China region -----------------------------------------------------------------


def test_minimax_cn_preset_is_pickable():
    p = preset("minimax-cn")
    assert p is not None
    assert ("minimax-cn", p.label, p.hint) in menu_choices()


def test_minimax_cn_uses_china_base_and_own_secret():
    p = preset("minimax-cn")
    assert p.base.get("api_base") == "https://api.minimaxi.com/v1"
    secrets = [f for f in p.fields if f.kind == "secret"]
    assert secrets and secrets[0].env == "MINIMAX_CN_API_KEY"
    assert secrets[0].env != preset("minimax").fields[0].env   # não reaproveita a chave global


def test_minimax_cn_builds_valid_provider_config():
    p = preset("minimax-cn")
    cfg = _build_one("minimax-cn", p.base)
    pc = cfg.providers["minimax-cn"]
    assert pc.api_base == "https://api.minimaxi.com/v1"
    assert pc.auth == "api_key"


# --- item 3: custom / "traga seu provider" reutilizável -------------------------------------------


def test_custom_preset_label_reads_as_bring_your_own_vendor():
    p = preset("custom")
    text = (p.label + " " + p.hint).lower()
    assert "token" in text or "api key" in text or "endpoint" in text


def test_custom_preset_can_be_added_under_arbitrary_ids():
    # a mesma preset "custom" deve persistir DUAS instâncias distintas (IDs diferentes) — a rota
    # "traga seu provider" existe pra multi-vendor, não só um custom global.
    p = preset("custom")
    base1 = dict(p.base, model="openai/vendor-a-model", api_base="https://vendor-a.example/v1",
                api_key_env="VENDOR_A_KEY")
    base2 = dict(p.base, model="openai/vendor-b-model", api_base="https://vendor-b.example/v1",
                api_key_env="VENDOR_B_KEY")
    raw = {"default_provider": "vendor-a",
           "providers": {"vendor-a": base1, "vendor-b": base2}}
    cfg = build_config(raw)
    assert cfg.providers["vendor-a"].api_base == "https://vendor-a.example/v1"
    assert cfg.providers["vendor-b"].api_base == "https://vendor-b.example/v1"


# --- item 4: xAI/Grok subscription (OAuth) ---------------------------------------------------------


def test_xai_oauth_preset_is_pickable_and_experimental():
    p = preset("xai-oauth")
    assert p is not None
    assert ("xai-oauth", p.label, p.hint) in menu_choices()
    assert p.base.get("experimental") is True


def test_xai_oauth_builds_valid_provider_config():
    p = preset("xai-oauth")
    cfg = _build_one("xai-oauth", p.base)
    pc = cfg.providers["xai-oauth"]
    assert pc.auth == "oauth_subscription"
    assert pc.oauth and pc.oauth["client_id"] == "b1a00492-073a-47ea-816f-4c329264a828"  # valor real do Hermes


# --- geral: todo preset novo/existente sobrevive a um build_config real --------------------------


def test_every_preset_builds_a_valid_provider_config():
    for p in PRESETS:
        base = dict(p.base)
        base.setdefault("model", (p.model_prefix or "") + "test-model")  # normalmente vem de _pick_model
        for f in p.fields:                     # secrets viram api_key_env; demais campos ganham default
            if f.kind == "secret":
                base["api_key_env"] = f.env
            elif f.default:
                base[f.key] = f.default
        cfg = _build_one(p.key, base)
        assert p.key in cfg.providers, p.key
