"""Multi-vendor: uma API key com caractere fora de latin-1 (CJK/emoji/NBSP colado) ou \\r\\n embutido derruba
o turno ANTES de chamar o modelo — httpx (litellm) e urllib (codex/minimax/oauth) levantam UnicodeEncodeError
ao montar o header. header_safe_key salva o que dá (tira quebras de paste) e DESCARTA o impossível → o pool
faz failover p/ a próxima chave válida em vez de estourar."""
from __future__ import annotations

from okami.llm.sanitize import header_safe_key


def test_plain_ascii_key_passes():
    assert header_safe_key("sk-abc123") == "sk-abc123"


def test_edge_whitespace_and_paste_breaks_are_salvaged():
    assert header_safe_key("  sk-abc123\n ") == "sk-abc123"
    assert header_safe_key("sk-abc\r\n123") == "sk-abc123"


def test_non_ascii_key_is_rejected():
    assert header_safe_key("sk-abc" + "中") is None      # CJK 中 → latin-1 estoura
    assert header_safe_key("sk-" + "\U0001f600") is None     # emoji


def test_internal_control_char_rejected():
    assert header_safe_key("sk-\x07abc") is None             # BEL control char


def test_key_pool_drops_unsafe_and_keeps_valid():
    from okami.config import ProviderConfig
    pc = ProviderConfig(name="p", model="m", api_keys=["sk-good", "sk-bad" + "中", "sk-good2"])
    pool = pc.key_pool()
    assert "sk-good" in pool and "sk-good2" in pool
    assert all("中" not in k for k in pool)              # a malformada não entra no pool
