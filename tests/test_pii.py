"""pii: redação de PII no prompt->LLM por plataforma (telefone + ids longos)."""

from __future__ import annotations

from okami.gateway.pii import PII_SAFE_PLATFORMS, hash_id, redact_pii


def test_safe_platforms_set():
    # plataformas onde o id cru NÃO é necessário p/ menção → pode mascarar
    assert "telegram" in PII_SAFE_PLATFORMS
    assert "whatsapp" in PII_SAFE_PLATFORMS
    assert "signal" in PII_SAFE_PLATFORMS
    assert "bluebubbles" in PII_SAFE_PLATFORMS
    # discord precisa de id numérico CRU p/ montar a menção (<@id>) → fora do set
    assert "discord" not in PII_SAFE_PLATFORMS


def test_masks_phone_on_safe_platform():
    out = redact_pii("ligue +55 11 99999-8888 agora", "telegram")
    assert "99999" not in out           # número some
    assert "[telefone]" in out          # vira placeholder
    assert "ligue" in out and "agora" in out  # texto comum intacto


def test_discord_keeps_text_intact():
    txt = "ligue +55 11 99999-8888 agora"
    assert redact_pii(txt, "discord") == txt  # id cru preservado p/ menção


def test_long_numeric_id_hashed_on_safe_platform():
    out = redact_pii("user 123456789 falou", "whatsapp")
    assert "123456789" not in out       # id longo (>=7 dígitos) some
    assert hash_id("123456789") in out  # trocado pelo hash determinístico


def test_short_numbers_survive():
    # número curto (<7 dígitos) não é id → fica (ex.: "ano 2026", "sala 42")
    out = redact_pii("sala 42 ano 2026", "telegram")
    assert "42" in out and "2026" in out


def test_hash_id_is_stable_and_short():
    a = hash_id("123456789")
    b = hash_id("123456789")
    assert a == b                       # determinístico
    assert len(a) == 8                  # sha256 hex[:8]
    assert hash_id("987654321") != a    # entradas distintas → hashes distintos


def test_failsafe_on_bad_input():
    # best-effort: nunca explode no caller
    assert redact_pii("", "telegram") == ""
    assert redact_pii(None, "telegram") is None
    assert redact_pii("texto", "") == "texto"
