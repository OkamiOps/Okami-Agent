"""i18n: EN é o default, PT disponível; resolução de locale, fallback e interpolação."""

from __future__ import annotations

import pytest

from okami import i18n


@pytest.fixture(autouse=True)
def _reset_lang():
    i18n.set_lang(None)          # estado limpo antes
    yield
    i18n.set_lang(None)          # e depois (não vaza locale entre testes)


def test_default_is_english():
    assert i18n.current_lang() == "en"
    assert i18n.t("chat.commands_header") == "📜 commands by category:"


def test_set_lang_switches_to_pt():
    i18n.set_lang("pt")
    assert i18n.current_lang() == "pt"
    assert i18n.t("chat.commands_header") == "📜 comandos por categoria:"


def test_env_var_resolves_locale(monkeypatch):
    i18n.set_lang(None)
    monkeypatch.setenv("OKAMI_LANG", "pt_BR")     # normaliza pt_BR → pt
    i18n._resolved = None                          # invalida o cache p/ reler o env
    assert i18n.current_lang() == "pt"
    i18n._resolved = None


def test_missing_key_falls_back_to_english_then_key():
    i18n.set_lang("pt")
    # chave só existe em EN (não no pt catalog) → cai p/ EN
    assert i18n.t("tui.help.col.does") == "o que faz"     # esta existe em pt
    # chave inexistente em qualquer catálogo → devolve a própria key (visível/debugável)
    assert i18n.t("nao.existe.essa.chave") == "nao.existe.essa.chave"


def test_interpolation():
    assert i18n.t("chat.help", agent="okami", ess="/new, /stop") == (
        "I'm the agent 'okami'. Send me a task.\nEssentials: /new, /stop\n/commands lists ALL by category.")


def test_unsupported_lang_ignored():
    i18n.set_lang("xx")           # idioma não suportado → ignora (volta ao default)
    assert i18n.current_lang() == "en"


def test_command_descriptions_localize():
    from okami import commands as c
    i18n.set_lang(None)
    assert c.desc_of(c.resolve("new")) == "start a new conversation (archives the current one)"
    assert c.category_label("session") == "session"
    i18n.set_lang("pt")
    assert c.desc_of(c.resolve("new")) == "começa uma conversa nova (arquiva a atual)"
    assert c.category_label("session") == "sessão"


def test_pt_catalog_covers_all_commands():
    # toda descrição de comando tem tradução PT (senão PT cairia em inglês — incompleto).
    from okami import commands as c
    from okami.locales.pt import MESSAGES as PT
    faltando = [cmd.name for cmd in c.COMMAND_REGISTRY if f"cmd.{cmd.name}" not in PT]
    assert not faltando, f"sem tradução PT: {faltando}"


def test_migrated_cli_keys_have_pt_translation():
    # INVARIANTE bilíngue: toda chave doctor./status./setup. usada no código TEM tradução PT
    # (senão usuário pt veria inglês). Guarda contra migração futura esquecer o catálogo.
    import pathlib
    import re

    from okami.locales.pt import MESSAGES
    files = ["okami/cli/commands/basics.py", "okami/cli/commands/misc.py", "okami/cli/commands/setup.py"]
    used: set[str] = set()
    for f in files:
        used |= set(re.findall(r'(?<![\w])t\(\s*"([a-z][a-z0-9_.]+)"', pathlib.Path(f).read_text(encoding="utf-8")))
    body = {k for k in used if k.split(".")[0] in ("doctor", "status", "setup")}
    missing = sorted(k for k in body if k not in MESSAGES)
    assert not missing, f"chaves sem tradução PT: {missing}"
