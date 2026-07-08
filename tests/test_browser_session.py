"""Item 18-continuidade — sessão de browser persistente (TDD).

Cobre:
  - BrowserSessionManager cria/reusa/fecha worker por session_id;
  - reap_once fecha sessão ociosa há mais de idle_timeout;
  - browse(session_id=...) reusa a MESMA page entre duas chamadas (2ª sem url reusa a atual);
  - refs [N] da sessão sobrevivem entre chamadas SEM depender de threading.local;
  - dialog (alert/confirm) é auto-dismissado e não trava a chamada.
"""
from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace

import pytest

from okami.integrations.browser_session import BrowserSessionManager, SessionError, _SessionWorker
from okami.integrations import browser as browser_mod


# ---------------------------------------------------------------------------
# fake Playwright thread-safe (cada _SessionWorker roda numa thread própria)
# ---------------------------------------------------------------------------
class _FakePage:
    def __init__(self):
        self.gotos = []
        self.clicked = []
        self.filled = []
        self.scrolled = []
        self.pressed = []
        self.went_back = 0
        self.url = ""
        self._dialog_cb = None
        self._body = "corpo inicial"

        class _Mouse:
            def wheel(self_inner, x, y):
                self.scrolled.append(y)

        class _Keyboard:
            def press(self_inner, key):
                self.pressed.append(key)

        self.mouse = _Mouse()
        self.keyboard = _Keyboard()

        class _AX:
            def snapshot(self_inner):
                return {"role": "WebArea", "name": "p", "children": [
                    {"role": "button", "name": "Ok"},
                ]}

        self.accessibility = _AX()

    def goto(self, url, timeout=None):
        self.gotos.append(url)
        self.url = url
        self._body = f"corpo de {url}"

    def inner_text(self, sel):
        return self._body

    def click(self, selector, timeout=None):
        self.clicked.append(selector)

    def fill(self, selector, text, timeout=None):
        self.filled.append((selector, text))

    def go_back(self, timeout=None):
        self.went_back += 1

    def evaluate(self, js):
        return "42"

    def wait_for_timeout(self, ms):
        pass

    def screenshot(self, path=None):
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\nfake")

    def on(self, event, cb):
        if event == "dialog":
            self._dialog_cb = cb

    def fire_dialog(self, dtype="alert", message="oi"):
        if self._dialog_cb:
            fake = SimpleNamespace(type=dtype, message=message,
                                   accept=lambda *a: None, dismiss=lambda *a: None)
            self._dialog_cb(fake)


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, page):
        self._page = page

    def launch_persistent_context(self, user_data_dir=None, **kw):
        return _FakeContext(self._page)


class _FakeSyncPlaywright:
    def __init__(self, page):
        self._cm = SimpleNamespace(chromium=_FakeChromium(page))

    def __enter__(self):
        return self._cm

    def __exit__(self, *a):
        return False


@pytest.fixture()
def fake_playwright(monkeypatch):
    """Injeta playwright.sync_api falso — thread-safe (cada worker abre sua própria _FakeSyncPlaywright,
    mas todas compartilham a MESMA _FakePage por padrão, salvo se o teste passar outra)."""
    page = _FakePage()
    fake_sync_api = SimpleNamespace(sync_playwright=lambda: _FakeSyncPlaywright(page))
    fake_pkg = SimpleNamespace(sync_api=fake_sync_api)
    monkeypatch.setitem(sys.modules, "playwright", fake_pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)
    return page


# ---------------------------------------------------------------------------
# BrowserSessionManager
# ---------------------------------------------------------------------------
def test_get_or_create_reusa_worker_do_mesmo_session_id(fake_playwright, tmp_path):
    mgr = BrowserSessionManager()
    w1 = mgr.get_or_create("chat-1", tmp_path)
    w2 = mgr.get_or_create("chat-1", tmp_path)
    assert w1 is w2
    mgr.close_all()


def test_session_ids_diferentes_dao_workers_diferentes(fake_playwright, tmp_path):
    mgr = BrowserSessionManager()
    w1 = mgr.get_or_create("chat-1", tmp_path)
    w2 = mgr.get_or_create("chat-2", tmp_path)
    assert w1 is not w2
    mgr.close_all()


def test_close_fecha_e_remove_a_sessao(fake_playwright, tmp_path):
    mgr = BrowserSessionManager()
    mgr.get_or_create("chat-1", tmp_path)
    assert mgr.close("chat-1") is True
    assert mgr.close("chat-1") is False    # já fechada → False
    assert "chat-1" not in mgr.active_ids()


def test_reap_once_fecha_sessao_ociosa(fake_playwright, tmp_path):
    mgr = BrowserSessionManager(idle_timeout=5)
    w = mgr.get_or_create("chat-1", tmp_path)
    w.last_used = time.time() - 100      # simula 100s de ociosidade (> idle_timeout=5)
    stale = mgr.reap_once()
    assert stale == ["chat-1"]
    assert "chat-1" not in mgr.active_ids()


def test_reap_once_preserva_sessao_ativa(fake_playwright, tmp_path):
    mgr = BrowserSessionManager(idle_timeout=999)
    mgr.get_or_create("chat-1", tmp_path)
    stale = mgr.reap_once()
    assert stale == []
    mgr.close_all()


def test_worker_falha_ao_iniciar_sem_playwright(tmp_path, monkeypatch):
    # sem fake_playwright instalado → ImportError dentro da thread → SessionError propaga ao chamador
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SessionError):
        _SessionWorker("chat-x", tmp_path)


# ---------------------------------------------------------------------------
# browse(session_id=...) — continuidade real via a API pública
# ---------------------------------------------------------------------------
def test_duas_chamadas_reusam_a_mesma_pagina(fake_playwright, tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    page = fake_playwright
    out1 = browser_mod.browse("https://example.com/login", action="read", session_id="conv-1")
    assert page.gotos == ["https://example.com/login"]
    assert "corpo de https://example.com/login" in out1

    # 2ª chamada SEM url — deve agir na página atual, sem re-navegar
    out2 = browser_mod.browse(action="snapshot", session_id="conv-1")
    assert page.gotos == ["https://example.com/login"]   # nenhum goto novo
    assert "[1]" in out2 and "Ok" in out2

    browser_mod._browse_session  # smoke: função existe (import não quebrou)
    from okami.integrations.browser_session import SESSIONS
    SESSIONS.close("conv-1")


def test_url_atual_aparece_no_retorno(fake_playwright, tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    out = browser_mod.browse("https://example.com/a", session_id="conv-url")
    assert "example.com/a" in out
    from okami.integrations.browser_session import SESSIONS
    SESSIONS.close("conv-url")


def test_click_por_ref_na_sessao_usa_refs_da_sessao_nao_thread_local(fake_playwright, tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    browser_mod.browse("https://example.com", action="snapshot", session_id="conv-refs")
    browser_mod.browse(action="click", selector="[1]", session_id="conv-refs")
    page = fake_playwright
    assert page.clicked, "click deveria ter resolvido o ref [1] via os refs DA SESSÃO"
    from okami.integrations.browser_session import SESSIONS
    SESSIONS.close("conv-refs")


def test_sem_url_e_sem_pagina_aberta_da_erro_claro(fake_playwright, tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    out = browser_mod.browse(action="read", session_id="conv-vazia")
    assert "url" in out.lower()
    from okami.integrations.browser_session import SESSIONS
    SESSIONS.close("conv-vazia")


# ---------------------------------------------------------------------------
# novas ações: scroll / back / press / eval
# ---------------------------------------------------------------------------
def test_scroll_chama_mouse_wheel(fake_playwright, tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    browser_mod.browse("https://example.com", action="scroll", text="500", session_id="conv-scroll")
    assert fake_playwright.scrolled == [500]
    from okami.integrations.browser_session import SESSIONS
    SESSIONS.close("conv-scroll")


def test_back_chama_go_back(fake_playwright, tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    browser_mod.browse("https://example.com", action="read", session_id="conv-back")
    browser_mod.browse(action="back", session_id="conv-back")
    assert fake_playwright.went_back == 1
    from okami.integrations.browser_session import SESSIONS
    SESSIONS.close("conv-back")


def test_press_chama_keyboard_press(fake_playwright, tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    browser_mod.browse("https://example.com", action="press", text="Enter", session_id="conv-press")
    assert fake_playwright.pressed == ["Enter"]
    from okami.integrations.browser_session import SESSIONS
    SESSIONS.close("conv-press")


def test_eval_roda_e_devolve_resultado(fake_playwright, tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    out = browser_mod.browse("https://example.com", action="eval", text="1+1", session_id="conv-eval")
    assert "42" in out
    from okami.integrations.browser_session import SESSIONS
    SESSIONS.close("conv-eval")


@pytest.mark.parametrize("js", [
    "document.cookie",
    "localStorage.getItem('token')",
    "fetch('http://169.254.169.254/latest/meta-data/')",
    "fetch('http://127.0.0.1:8080/admin')",
])
def test_eval_guard_bloqueia_exfil(fake_playwright, tmp_path, monkeypatch, js):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    out = browser_mod.browse("https://example.com", action="eval", text=js, session_id="conv-eval-guard")
    assert "bloqueado" in out.lower()
    from okami.integrations.browser_session import SESSIONS
    SESSIONS.close("conv-eval-guard")


def test_eval_guard_direto():
    from okami.integrations.browser import guard_eval_script
    assert guard_eval_script("document.cookie") is not None
    assert guard_eval_script("1+1") is None
    assert guard_eval_script("fetch('https://api.example.com/data')") is None  # público → liberado


# ---------------------------------------------------------------------------
# screenshot
# ---------------------------------------------------------------------------
def test_screenshot_salva_arquivo(fake_playwright, tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    out_path = tmp_path / "shot.png"
    out = browser_mod.browse("https://example.com", action="screenshot", screenshot=str(out_path),
                             session_id="conv-shot")
    assert "salvo" in out
    assert out_path.exists()
    from okami.integrations.browser_session import SESSIONS
    SESSIONS.close("conv-shot")


# ---------------------------------------------------------------------------
# dialog auto-dismiss
# ---------------------------------------------------------------------------
def test_dialog_auto_dismiss_nao_trava(fake_playwright, tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    from okami.integrations.browser_session import SESSIONS
    worker = SESSIONS.get_or_create("conv-dialog", tmp_path / "profile")
    assert worker.dialog_policy == "dismiss"

    # dispara um dialog na thread da sessão (via call, pra rodar no contexto certo) — não deve travar
    def _trigger(w):
        w.page.fire_dialog("confirm", "tem certeza?")
        return "ok"

    result = worker.call(_trigger, timeout=5)
    assert result == "ok"
    assert worker.last_dialog is not None
    assert worker.last_dialog.handled_as == "dismiss"
    SESSIONS.close("conv-dialog")


def test_dialog_policy_accept_explicito(fake_playwright, tmp_path, monkeypatch):
    monkeypatch.setenv("OKAMI_HOME", str(tmp_path))
    from okami.integrations.browser_session import SESSIONS
    worker = SESSIONS.get_or_create("conv-dialog-accept", tmp_path / "profile", dialog_policy="accept")
    assert worker.dialog_policy == "accept"
    SESSIONS.close("conv-dialog-accept")
