"""Windows: o console às vezes injeta surrogates SOLITÁRIOS (U+D800–U+DFFF) no input (emoji/colagem).
Eles não são UTF-8 válido → estouram QUALQUER .encode('utf-8'): histórico do prompt_toolkit, print do
Rich, e o JSON enviado pro LLM. Bug real (Python 3.14 no Windows): 'utf-8 codec can't encode characters
... surrogates not allowed'. safe_text() troca por U+FFFD e mata o crash na origem.
"""
from __future__ import annotations


def test_safe_text_strips_lone_surrogates_and_is_encodable():
    from okami.core.redact import safe_text
    bad = "oi \ud83d tudo \ud800 bem"          # surrogates solitários
    out = safe_text(bad)
    out.encode("utf-8")                          # NÃO pode estourar
    assert "\ud800" not in out and "\ud83d" not in out and "bem" in out


def test_safe_text_keeps_normal_text_and_real_emoji():
    from okami.core.redact import safe_text
    assert safe_text("ascii ok") == "ascii ok"
    assert safe_text("café 🐺 ✓") == "café 🐺 ✓"   # emoji VÁLIDO (par já combinado) intacto
    assert safe_text("") == ""


def test_redacting_history_survives_surrogate_input(tmp_path):
    # antes: UnicodeEncodeError dentro do store_string → crashava o REPL ao dar Enter.
    from okami.cli.commands.chat import _make_redacting_history
    h = _make_redacting_history(str(tmp_path / "hist"))
    h.store_string("linha com \ud800 surrogate")     # não pode levantar
    data = (tmp_path / "hist").read_text(encoding="utf-8")
    assert "surrogate" in data
