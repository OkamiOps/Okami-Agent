"""Paridade Hermes (PLATFORM_HINTS): canal que NÃO renderiza markdown (email/api/webhook) tem que receber
DIREÇÃO de texto puro — não o esqueleto com TABELA pipe. Antes, email/api/webhook caíam no _delivery_full
e o modelo era mandado emitir '| col | col |' → lixo no email/SMS. (Hermes: 'do not use markdown')."""
from __future__ import annotations

from okami.core.harness.style import model_family_guidance, style_block

_TABLE = "| suíte | passou | falhou |"


def test_email_surface_is_plaintext_no_tables():
    s = style_block("email")
    assert _TABLE not in s                                  # email é texto puro → SEM tabela markdown
    assert "texto puro" in s.lower()


def test_api_and_webhook_are_plaintext():
    assert _TABLE not in style_block("api")                # renderer desconhecido → texto puro (Hermes)
    assert _TABLE not in style_block("webhook")


def test_cli_and_telegram_still_get_tables():
    assert _TABLE in style_block("cli")                    # terminal renderiza tabela (inalterado)
    assert _TABLE in style_block("telegram")               # telegram converte tabela (mantido)


def test_gemini_family_has_dependency_check():
    g = model_family_guidance("gemini-3-pro").lower()
    assert "manifesto" in g or "requirements" in g or "package.json" in g
