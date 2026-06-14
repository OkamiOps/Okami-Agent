"""Item 18 — browser a11y snapshot + contexto persistente (TDD).

Cobre três frentes:
  - sem Playwright → cai p/ fetch read-only (silencioso), preservando o comportamento atual;
  - launch_persistent_context é chamado com okami_home()/browser_profile (sites logados);
  - action=snapshot numera elementos interativos [N] e click/fill resolvem um ref [N] via mapa.
Casos com Chromium real são skipados quando Playwright está ausente.
"""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

from okami.integrations import browser as browser_mod

HAS_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None


# ---------------------------------------------------------------------------
# sem Playwright → fetch read-only silencioso (monkeypatch do import)
# ---------------------------------------------------------------------------
def test_browse_sem_playwright_cai_para_fetch(monkeypatch):
    """ImportError no sync_playwright deve degradar p/ fetch(), sem estourar."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    called = {}

    def fake_fetch(url, max_chars=6000):
        called["url"] = url
        return "TEXTO VIA FETCH"

    monkeypatch.setattr(browser_mod, "fetch", fake_fetch)
    out = browser_mod.browse("https://example.com", action="read")
    assert out == "TEXTO VIA FETCH"
    assert called["url"] == "https://example.com"


def test_browse_url_recusada_nao_chega_no_playwright(monkeypatch):
    """Guard SSRF preservado: URL privada é recusada antes de qualquer navegação."""
    out = browser_mod.browse("http://169.254.169.254/latest/meta-data/")
    assert "recusada" in out.lower()


# ---------------------------------------------------------------------------
# launch_persistent_context com okami_home()/browser_profile (mock sync_playwright)
# ---------------------------------------------------------------------------
class _FakePage:
    def __init__(self):
        self.gotos = []
        self._text = "corpo da pagina"

    def goto(self, url, timeout=None):
        self.gotos.append(url)

    def inner_text(self, sel):
        return self._text


class _FakeAXPage(_FakePage):
    """Page com accessibility.snapshot() p/ exercitar o snapshot numerado."""

    def __init__(self, tree):
        super().__init__()
        self._tree = tree
        self.clicked = []
        self.filled = []

        class _AX:
            def __init__(self, tree):
                self._tree = tree

            def snapshot(self_inner):
                return self_inner._tree

        self.accessibility = _AX(tree)

    def click(self, selector, timeout=None):
        self.clicked.append(selector)

    def fill(self, selector, text, timeout=None):
        self.filled.append((selector, text))


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def pages(self):
        return [self._page]

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, page, sink):
        self._page = page
        self._sink = sink

    def launch_persistent_context(self, user_data_dir=None, **kw):
        self._sink["user_data_dir"] = user_data_dir
        return _FakeContext(self._page)


class _FakeSyncPlaywright:
    def __init__(self, page, sink):
        self._cm = SimpleNamespace(chromium=_FakeChromium(page, sink))

    def __enter__(self):
        return self._cm

    def __exit__(self, *a):
        return False


def _install_fake_playwright(monkeypatch, page, sink):
    """Injeta um módulo playwright.sync_api falso p/ capturar a chamada."""
    fake_sync_api = SimpleNamespace(sync_playwright=lambda: _FakeSyncPlaywright(page, sink))
    fake_pkg = SimpleNamespace(sync_api=fake_sync_api)
    monkeypatch.setitem(sys.modules, "playwright", fake_pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)


def test_persistent_context_usa_browser_profile_da_home(monkeypatch, tmp_path):
    from okami.home import okami_home

    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    sink = {}
    page = _FakePage()
    _install_fake_playwright(monkeypatch, page, sink)

    out = browser_mod.browse("https://example.com", action="read")
    assert "user_data_dir" in sink
    expected = okami_home() / "browser_profile"
    assert str(sink["user_data_dir"]) == str(expected)
    assert page.gotos == ["https://example.com"]
    assert "corpo da pagina" in out


# ---------------------------------------------------------------------------
# snapshot numerado + ref [N] em click/fill
# ---------------------------------------------------------------------------
_TREE = {
    "role": "WebArea",
    "name": "pagina",
    "children": [
        {"role": "link", "name": "Entrar"},
        {"role": "textbox", "name": "Usuário"},
        {"role": "button", "name": "Enviar"},
        {"role": "text", "name": "rodapé"},  # NÃO interativo — não numera
    ],
}


def test_snapshot_numera_interativos(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    sink = {}
    page = _FakeAXPage(_TREE)
    _install_fake_playwright(monkeypatch, page, sink)

    out = browser_mod.browse("https://example.com", action="snapshot")
    # interativos viram [1] [2] [3]; o "text" não-interativo fica de fora
    assert "[1]" in out and "[2]" in out and "[3]" in out
    assert "Entrar" in out and "Usuário" in out and "Enviar" in out
    assert "[4]" not in out


def test_click_por_ref_resolve_via_mapa(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    sink = {}
    page = _FakeAXPage(_TREE)
    _install_fake_playwright(monkeypatch, page, sink)

    # primeiro snapshot popula o cache ref->elemento
    browser_mod.browse("https://example.com", action="snapshot")
    # depois um click usando o ref [3] (o botão Enviar) — sem selector
    browser_mod.browse("https://example.com", action="click", selector="[3]")
    assert page.clicked, "click deveria ter sido chamado resolvendo o ref"
    # o seletor resolvido deve mirar o botão 'Enviar'
    resolved = page.clicked[-1]
    assert "Enviar" in resolved or "button" in resolved.lower()


def test_fill_por_ref_resolve_via_mapa(monkeypatch, tmp_path):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    sink = {}
    page = _FakeAXPage(_TREE)
    _install_fake_playwright(monkeypatch, page, sink)

    browser_mod.browse("https://example.com", action="snapshot")
    browser_mod.browse("https://example.com", action="fill", selector="[2]", text="marcos")
    assert page.filled, "fill deveria ter sido chamado resolvendo o ref"
    sel, txt = page.filled[-1]
    assert txt == "marcos"
    assert "Usuário" in sel or "textbox" in sel.lower()


def test_selector_css_continua_funcionando(monkeypatch, tmp_path):
    """Fallback: um selector que NÃO é [N] passa direto ao Playwright (compat)."""
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    sink = {}
    page = _FakeAXPage(_TREE)
    _install_fake_playwright(monkeypatch, page, sink)

    browser_mod.browse("https://example.com", action="click", selector="#botao-css")
    assert page.clicked[-1] == "#botao-css"


# ---------------------------------------------------------------------------
# tool Browse: args_schema estendido com snapshot + ref
# ---------------------------------------------------------------------------
def test_browse_tool_args_schema_tem_snapshot_e_ref():
    from okami.core.tools.agentic import Browse

    schema = Browse.args_schema
    assert "snapshot" in schema.get("action", "")
    # o ref [N] deve estar documentado em algum campo (action ou selector)
    blob = " ".join(str(v) for v in schema.values()).lower()
    assert "ref" in blob or "[n]" in blob


# ---------------------------------------------------------------------------
# Chromium REAL (só com Playwright instalado)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="playwright ausente")
def test_snapshot_real_chromium(tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    html = "data:text/html,<a href='#'>Login</a><button>Ok</button>"
    try:
        out = browser_mod.browse(html, action="snapshot")
    except Exception as e:  # noqa: BLE001 — Chromium pode não estar baixado no CI
        pytest.skip(f"chromium indisponível: {e}")
    assert "[1]" in out
