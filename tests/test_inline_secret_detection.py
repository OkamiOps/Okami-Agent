"""detect_inline_secrets / sanitize_inline_secrets (okami/core/redact.py) — captura de credencial
ALTA CONFIANÇA no INBOUND, antes de o texto tocar o modelo (diretiva do dono "Só no cofre, nunca no
LLM"). Conservador de propósito: só prefixo de chave conhecido ou "NOME=valor"/"NOME:valor" explícito
disparam — frase solta com senha curta (linguagem natural) NUNCA aciona (evita falso-positivo)."""
from __future__ import annotations

from okami.core.redact import detect_inline_secrets, sanitize_inline_secrets


def test_detects_github_token_by_prefix():
    text = "aqui está minha chave: ghp_abcdef0123456789ABCDEF0123456789, pode usar"  # pragma: allowlist secret
    matches = detect_inline_secrets(text)
    assert len(matches) == 1
    assert matches[0]["name"] == "GITHUB_TOKEN"
    assert matches[0]["value"] == "ghp_abcdef0123456789ABCDEF0123456789"  # pragma: allowlist secret


def test_detects_openai_style_key():
    text = "OPENAI_API_KEY=sk-liveabcdef0123456789ABCDEF01"  # pragma: allowlist secret
    matches = detect_inline_secrets(text)
    assert len(matches) == 1
    assert matches[0]["name"] == "OPENAI_API_KEY"


def test_detects_anthropic_key_before_generic_sk():
    text = "sk-ant-abcdef0123456789ABCDEF0123456789"  # pragma: allowlist secret
    matches = detect_inline_secrets(text)
    assert len(matches) == 1
    assert matches[0]["name"] == "ANTHROPIC_API_KEY"


def test_detects_explicit_assignment_with_provider_hint():
    # NOME=valor genérico (sem provider no rótulo) + palavra "github" em algum lugar da mensagem →
    # usa o hint de provider pra nomear certo (em vez de "API_KEY" cru).
    text = "para o github, API_KEY: abcXYZ0123456789supersecreto"
    matches = detect_inline_secrets(text)
    assert len(matches) == 1
    assert matches[0]["name"] == "GITHUB_TOKEN"
    assert matches[0]["value"] == "abcXYZ0123456789supersecreto"


def test_detects_explicit_assignment_without_provider_hint_normalizes_label():
    text = "API_KEY=abcXYZ0123456789supersecreto"
    matches = detect_inline_secrets(text)
    assert len(matches) == 1
    assert matches[0]["name"] == "API_KEY"


def test_no_false_positive_on_natural_language_short_password():
    assert detect_inline_secrets("minha senha é hunter2") == []
    assert detect_inline_secrets("my password is hunter2") == []


def test_no_false_positive_on_normal_message():
    assert detect_inline_secrets("oi, tudo bem? cria um repo pra mim") == []
    assert detect_inline_secrets("roda os testes e me diz o resultado") == []


def test_no_false_positive_on_numeric_counts():
    assert detect_inline_secrets("tokens_in: 2650, tokens_out: 340") == []


def test_sanitize_replaces_value_never_returns_it():
    secret = "ghp_abcdef0123456789ABCDEF0123456789"  # pragma: allowlist secret
    text = f"guarda essa chave: {secret} e depois cria o repo"
    sanitized, matches, note = sanitize_inline_secrets(text)
    assert secret not in sanitized
    assert "cria o repo" in sanitized                      # resto da instrução preservado
    assert matches[0]["value"] == secret                   # valor cru só no retorno interno p/ o vault
    assert "GITHUB_TOKEN" in note


def test_sanitize_noop_when_no_secret():
    text = "oi, bom dia"
    sanitized, matches, note = sanitize_inline_secrets(text)
    assert sanitized == text
    assert matches == []
    assert note == ""


def test_multiple_secrets_in_one_message():
    t1 = "ghp_abcdef0123456789ABCDEF0123456789"      # pragma: allowlist secret
    t2 = "sk-ant-zzzzzz0123456789ABCDEF0123456789"    # pragma: allowlist secret
    text = f"github: {t1} e anthropic: {t2}"
    sanitized, matches, note = sanitize_inline_secrets(text)
    assert t1 not in sanitized and t2 not in sanitized
    names = {m["name"] for m in matches}
    assert names == {"GITHUB_TOKEN", "ANTHROPIC_API_KEY"}
