"""Slash command registry (estilo Hermes CommandDef): resolução de alias, did-you-mean, dispatch."""

from __future__ import annotations
import pytest

from okami import commands as cmds
from okami.gateway import AgentEndpoint


# ----------------------------------------------------------------- registro (puro)
def test_registry_resolve_and_suggest():
    assert cmds.resolve("/New").name == "new"           # case-insensitive + sem "/"
    assert cmds.resolve("reset").name == "new"          # alias
    assert cmds.resolve("/m").name == "model"           # alias curto
    assert cmds.resolve("/inexistente") is None
    assert cmds.suggest("/mod") == ["model", "models"]  # prefix-match p/ did-you-mean
    assert "usage" in cmds.suggest("/usag")


def test_registry_help_and_autocomplete():
    cats = cmds.by_category()
    assert "session" in cats and "model" in cats and "info" in cats   # chaves de categoria estáveis (EN)
    assert any(c.name == "new" for c in cats["session"])
    names = cmds.all_slash_names()
    assert "/new" in names and "/reset" in names        # inclui aliases
    assert cmds.help_lines()                             # não-vazio
    assert all(c.tier == "essential" for cs in cmds.by_category(tier="essential").values() for c in cs)


# ----------------------------------------------------------------- dispatch no gateway
class _Fake:
    name = "fake"

    def __init__(self):
        self.sent: list[str] = []

    def send(self, cid, text):
        self.sent.append(text)

    def send_audio(self, cid, p):
        pass

    def poll(self):
        return []

    def allowed(self, cid):
        return True


def _ep(tmp_path):
    ch = _Fake()
    ep = AgentEndpoint("okami", None, tmp_path, ch, run_task=lambda *a, **k: None,
                       spawn=lambda fn: fn())
    return ep, ch


def test_new_commands_dispatch(tmp_path):
    ep, ch = _ep(tmp_path)
    ep.handle("c1", "/commands")
    assert "comandos por categoria" in ch.sent[-1] and "sessão:" in ch.sent[-1]   # módulo sob locale pt
    ep.handle("c1", "/tools")
    assert "ferramentas:" in ch.sent[-1] and "read_file" in ch.sent[-1]
    ep.handle("c1", "/whoami")
    assert "chat id: c1" in ch.sent[-1]
    ep.handle("c1", "/usage")
    assert "sem tokens" in ch.sent[-1]


def test_alias_canonicalized_and_unknown_suggests(tmp_path):
    ep, ch = _ep(tmp_path)
    ep.handle("c1", "/reset")                            # alias de /new
    assert "reiniciada" in ch.sent[-1]
    ep.handle("c1", "/usag")                             # typo → did-you-mean
    assert "desconhecido" in ch.sent[-1] and "/usage" in ch.sent[-1]


def test_model_show_and_switch(tmp_path):
    ep, ch = _ep(tmp_path)
    ep.handle("c1", "/model")
    assert "modelo:" in ch.sent[-1]
    ep.handle("c1", "/model openai-codex/gpt-5.4")
    assert ep.session("c1").model_override == "openai-codex/gpt-5.4"
    assert "→ openai-codex/gpt-5.4" in ch.sent[-1]


@pytest.fixture(autouse=True)
def _i18n_pt_locale():
    """i18n: estes testes foram escritos com as respostas do gateway em PT. Força o locale `pt` (o
    comportamento EN-default é coberto por test_i18n). Reseta após cada teste."""
    import okami.i18n as _i18n
    _i18n.set_lang("pt")
    yield
    _i18n.set_lang(None)
