"""Browser automation (§13). Com Playwright (`pip install ".[browser]"`): navega, clica, preenche,
screenshot. SEM Playwright: degrada p/ fetch read-only (urllib + strip de HTML) — ainda lê páginas.

Item 18 — a11y + contexto persistente:
  - action="snapshot" tira um page.accessibility.snapshot() e numera os elementos INTERATIVOS [N],
    cacheando um mapa ref->elemento na page persistente (de módulo) p/ a sessão. O modelo então
    clica/preenche por ref ([N]) em vez de adivinhar seletor CSS — selector continua como fallback.
  - usa launch_persistent_context(user_data_dir=okami_home()/"browser_profile") no lugar de
    launch()+new_page(), pra você ficar LOGADO entre chamadas (sites que exigem sessão).
"""

from __future__ import annotations

import random
import re
import threading
import time

_MAX = 6000
_TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})   # repetível; 403/404/401 = não adianta

# Roles da árvore de acessibilidade que valem um [N] clicável/preenchível.
_INTERACTIVE_ROLES = frozenset({
    "link", "button", "textbox", "searchbox", "combobox", "checkbox",
    "radio", "switch", "menuitem", "tab", "option", "slider", "spinbutton",
})

# Mapa ref->elemento da ÚLTIMA snapshot, p/ resolver [N] em click/fill. POR THREAD (threading.local):
# sobrevive entre chamadas de browse() na MESMA thread (a "page persistente" da sessão), mas dois
# subagentes em paralelo NÃO se sobrescrevem — o snapshot de um não apaga os refs do outro.
_REFS_TLS = threading.local()


def _last_refs() -> dict[int, dict]:
    d = getattr(_REFS_TLS, "refs", None)
    if d is None:
        d = _REFS_TLS.refs = {}
    return d


def _strip_html(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _transient(exc) -> tuple[bool, float]:
    """(repetir?, retry_after_seg). HTTP 429/5xx + timeout/conexão = transitório; 403/404/401 = permanente."""
    import socket
    import urllib.error
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in _TRANSIENT_STATUS:
            ra = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
            try:
                return True, min(float(ra), 30.0) if ra and str(ra).strip().isdigit() else 0.0
            except (TypeError, ValueError):
                return True, 0.0
        return False, 0.0                              # 403/404/401/410 → não adianta repetir
    return isinstance(exc, (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError)), 0.0


def fetch(url: str, max_chars: int = _MAX, *, attempts: int = 3) -> str:
    """Busca read-only com RETRY/backoff em erro transitório (429/5xx/timeout) — numa VPS a rede oscila e
    fonte com rate-limit não pode matar a tarefa no 1º erro. Erro permanente (403/404) falha na hora."""
    from okami.core.net_guard import BROWSER_HEADERS, BlockedURL, guarded_urlopen
    last = ""
    for i in range(max(1, attempts)):
        try:
            with guarded_urlopen(url, timeout=20, headers=dict(BROWSER_HEADERS)) as r:  # #6 anti-SSRF · UA real
                return _strip_html(r.read(300_000).decode("utf-8", "ignore"))[:max_chars]
        except BlockedURL as e:
            return f"(URL recusada: {e})"
        except Exception as e:  # noqa: BLE001
            last = f"(erro ao buscar {url}: {e})"
            retry, retry_after = _transient(e)
            if not retry or i == attempts - 1:
                return last
            time.sleep(retry_after or min(2 ** i + random.random(), 8.0))   # backoff exp + jitter, teto 8s
    return last


# marcadores de "preciso de um browser de verdade": desafio de bot ou página que só hidrata via JS.
_JS_BLOCK_MARKERS = ("just a moment", "checking your browser", "enable javascript", "habilite o javascript",
                     "cf-browser-verification", "please enable cookies", "verifying you are human",
                     "verificando que você", "captcha", "attention required")


def _looks_blocked_or_js(text: str) -> bool:
    """O resultado estático parece bloqueio/casca-de-JS (vale tentar o browser real)?"""
    t = (text or "").strip()
    if t.startswith("(erro ao buscar"):
        return True                                   # 403/5xx/rede → browser real pode passar
    if len(t) < 200:
        return True                                   # casca de JS / página praticamente vazia
    low = t.lower()
    return any(m in low for m in _JS_BLOCK_MARKERS)


def _render_js(url: str, max_chars: int = _MAX) -> str | None:
    """Renderiza a página num browser REAL (Playwright, contexto persistente p/ login/cookies) e devolve
    o texto do body. None se Playwright indisponível ou se falhar (caller cai no estático)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    from okami.core.net_guard import BlockedURL, validate_public_url
    try:
        validate_public_url(url)                      # #6 anti-SSRF vale tb p/ o goto do Playwright
    except BlockedURL:
        return None
    from okami.home import okami_home
    profile = okami_home() / "browser_profile"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(user_data_dir=str(profile), headless=True)
            try:
                page = context.new_page()
                page.goto(url, timeout=30000)
                page.wait_for_timeout(800)            # deixa o JS hidratar um pouco (preço/conteúdo dinâmico)
                return page.inner_text("body")[:max_chars]
            finally:
                context.close()
    except Exception:  # noqa: BLE001 — browser falhou → caller usa o estático
        return None


def smart_fetch(url: str, max_chars: int = _MAX) -> str:
    """ESTÁTICO primeiro; se vier bloqueado/vazio/casca-de-JS (403, Cloudflare, corpo minúsculo), re-tenta
    no browser REAL (Playwright) que renderiza JS e passa bloqueios brandos. Sem Playwright → estático
    mesmo. Bloqueio SSRF (URL recusada) NÃO re-tenta (o browser também barraria). Resolve grande parte do
    'webfetch não pega o conteúdo'; ainda NÃO vence captcha (decisão pendente do dono)."""
    static = fetch(url, max_chars)
    if static.startswith("(URL recusada"):
        return static
    if not _looks_blocked_or_js(static):
        return static
    rendered = _render_js(url, max_chars)
    if rendered and len(rendered.strip()) > len(static.strip()):
        return rendered                               # browser trouxe mais conteúdo → usa ele
    return static


# --- guarda do action=eval: bloqueia leitura de cookie/storage e fetch p/ endereço privado -------
_EVAL_STORAGE_RE = re.compile(r"document\.cookie|localStorage|sessionStorage|indexedDB", re.I)
_EVAL_PRIVATE_FETCH_RE = re.compile(
    r"(fetch|XMLHttpRequest|axios)\s*\(?\s*['\"`]?(https?://)?"
    r"(127\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|169\.254\.|localhost|0\.0\.0\.0|\[::1\])",
    re.I,
)


def guard_eval_script(js: str) -> str | None:
    """None = liberado. String = motivo do bloqueio (script NÃO roda). action=eval executa JS ARBITRÁRIO
    na página — sem isto, prompt injection na própria página manda ler document.cookie/localStorage
    (rouba sessão) ou faz fetch() pra endereço privado (SSRF por dentro do browser, contorna o net_guard
    que só vigia o goto)."""
    if not isinstance(js, str) or not js.strip():
        return "script vazio"
    if _EVAL_STORAGE_RE.search(js):
        return "eval bloqueado: acessa cookie/localStorage/sessionStorage/indexedDB (risco de exfil de sessão)"
    if _EVAL_PRIVATE_FETCH_RE.search(js):
        return "eval bloqueado: fetch/XHR/axios pra endereço privado/local (SSRF via JS da página)"
    return None


def _walk_interactive(node: dict, out: list[dict]) -> None:
    """Achata a árvore de a11y mantendo só nós interativos (DFS, ordem de leitura)."""
    if not isinstance(node, dict):
        return
    role = str(node.get("role", "")).lower()
    name = str(node.get("name", "")).strip()
    if role in _INTERACTIVE_ROLES and name:
        out.append({"role": role, "name": name})
    for child in node.get("children", []) or []:
        _walk_interactive(child, out)


def _ref_selector(el: dict) -> str:
    """Traduz um elemento da snapshot num seletor Playwright por papel+nome acessível.
    Usa get_by_role quando o page suportar; senão devolve uma string textual estável."""
    role, name = el.get("role", ""), el.get("name", "")
    # `role=button[name="Enviar"]` é o seletor de engine ARIA do Playwright (estável p/ a11y).
    safe = name.replace('"', '\\"')
    return f'role={role}[name="{safe}"]'


def _snapshot(page, max_chars: int, refs: dict[int, dict] | None = None) -> str:
    """Numera os interativos [N], popula `refs` (thread-local por default; da SESSÃO quando session_id é
    usado — item 18-continuidade) e devolve o mapa legível + texto da página."""
    if refs is None:
        refs = _last_refs()
    refs.clear()
    tree = page.accessibility.snapshot()
    items: list[dict] = []
    if tree:
        _walk_interactive(tree, items)
    linhas = []
    for i, el in enumerate(items, start=1):
        refs[i] = el
        linhas.append(f"[{i}] {el['role']}: {el['name']}")
    mapa = "\n".join(linhas) or "(nenhum elemento interativo encontrado)"
    corpo = ""
    try:
        corpo = page.inner_text("body")
    except Exception:  # noqa: BLE001 — algumas páginas/data-urls não têm body navegável
        corpo = ""
    cabecalho = "ELEMENTOS INTERATIVOS (use o [N] como `selector` em click/fill):\n" + mapa
    if corpo:
        return (cabecalho + "\n\n--- TEXTO DA PÁGINA ---\n" + corpo)[:max_chars]
    return cabecalho[:max_chars]


def _resolve_ref(selector: str | None, refs: dict[int, dict] | None = None) -> str | None:
    """Se `selector` for um ref [N] da última snapshot, devolve o seletor real; senão devolve-o
    intacto (fallback CSS/seletor cru). Ref desconhecido vira None (deixa o chamador avisar)."""
    if not selector:
        return selector
    m = re.fullmatch(r"\s*\[(\d+)\]\s*", selector)
    if not m:
        return selector                                # não é ref → passa direto (compat)
    el = (refs if refs is not None else _last_refs()).get(int(m.group(1)))
    if el is None:
        return None                                    # ref expirado/inexistente
    return _ref_selector(el)


_SESSION_ACTIONS = frozenset({
    "read", "open", "snapshot", "click", "fill", "screenshot", "scroll", "back", "press", "eval",
})


def _current_url(page) -> str:
    try:
        return page.url
    except Exception:  # noqa: BLE001
        return ""


def _act_on_page(page, action: str, sel: str | None, text: str | None, screenshot: str | None,
                 max_chars: int, refs: dict[int, dict] | None) -> str:
    """Executa UMA ação sobre uma page já navegada e devolve o texto/URL resultante. Compartilhado
    pelo caminho legado (1 tiro) e pelo caminho de sessão (persistente)."""
    if action == "snapshot":
        return _snapshot(page, max_chars, refs)
    if action == "click" and sel:
        page.click(sel, timeout=10000)
    elif action == "fill" and sel:
        page.fill(sel, text or "", timeout=10000)
    elif action == "screenshot" and screenshot:
        page.screenshot(path=screenshot)
        return f"screenshot salvo: {screenshot}\n[URL atual: {_current_url(page)}]"
    elif action == "scroll":
        amount = 800
        try:
            amount = int(text) if text else 800
        except (TypeError, ValueError):
            amount = 800
        page.mouse.wheel(0, amount)
        page.wait_for_timeout(200)
    elif action == "back":
        page.go_back(timeout=15000)
    elif action == "press" and text:
        page.keyboard.press(text)
    elif action == "eval":
        reason = guard_eval_script(text or "")
        if reason:
            return f"({reason})"
        try:
            result = page.evaluate(text or "")
        except Exception as e:  # noqa: BLE001
            return f"(eval falhou: {e})"
        return f"{result}\n[URL atual: {_current_url(page)}]"[:max_chars]
    body = ""
    try:
        body = page.inner_text("body")[:max_chars]
    except Exception:  # noqa: BLE001
        body = ""
    return f"{body}\n\n[URL atual: {_current_url(page)}]"


def _browse_oneshot(url: str, action: str, selector: str | None, text: str | None,
                    screenshot: str | None, max_chars: int) -> str:
    """Comportamento ORIGINAL (pré item 18-continuidade): abre um Chromium, faz 1 ação, fecha. Usado
    quando `session_id` não é passado (compat retroativo — é o caminho que os testes existentes e
    chamadores diretos de `browse()` exercitam)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return fetch(url, max_chars)                  # sem Playwright → read-only (silencioso)
    from okami.home import okami_home
    profile = okami_home() / "browser_profile"        # sessão persistente p/ sites logados
    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # contexto persistente = cookies/login sobrevivem entre chamadas (no lugar de launch()+new_page())
        context = p.chromium.launch_persistent_context(user_data_dir=str(profile), headless=True)  # VPS sem display
        try:
            page = context.new_page()
            page.goto(url, timeout=30000)
            sel = _resolve_ref(selector)
            if selector and sel is None:              # era um ref [N] que não existe mais
                return ("ref desconhecido — rode action=snapshot de novo p/ renumerar os elementos "
                        f"(a página pode ter mudado): {selector}")
            if action == "snapshot":
                return _snapshot(page, max_chars)
            if action == "click" and sel:
                page.click(sel, timeout=10000)
            elif action == "fill" and sel:
                page.fill(sel, text or "", timeout=10000)
            elif action == "screenshot" and screenshot:
                page.screenshot(path=screenshot)
                return f"screenshot salvo: {screenshot}"
            return page.inner_text("body")[:max_chars]
        finally:
            context.close()


def _browse_session(session_id: str, url: str | None, action: str, selector: str | None,
                    text: str | None, screenshot: str | None, max_chars: int,
                    dialog_policy: str | None) -> str:
    """Caminho de sessão PERSISTENTE (item 18-continuidade): reusa o Chromium/página de `session_id`
    entre chamadas — "clica login → cai no dashboard → clica relatório" sem re-navegar do zero. Só faz
    goto quando: (a) é a 1ª chamada da sessão, (b) action é read/open, ou (c) `url` mudou."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401 — só p/ checar disponibilidade
    except ImportError:
        if url:
            return fetch(url, max_chars)              # sem Playwright → read-only (silencioso)
        return "(Playwright indisponível — sem sessão de browser)"
    from okami.home import okami_home
    from okami.integrations.browser_session import SESSIONS, SessionError
    profile = okami_home() / "browser_profile"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        worker = SESSIONS.get_or_create(session_id, profile, dialog_policy=dialog_policy or "dismiss")
    except SessionError as e:
        return f"(sessão de browser indisponível: {e})"
    if dialog_policy:
        worker.dialog_policy = dialog_policy

    def _op(w):
        page = w.page
        needs_goto = url is not None and (w.current_url is None or action in ("read", "open")
                                          or url != w.current_url)
        if needs_goto:
            if url is None:
                raise ValueError("browse: sem 'url' e sem página aberta nesta sessão — informe url.")
            page.goto(url, timeout=30000)
            w.current_url = url
        elif w.current_url is None and url is None:
            raise ValueError("browse: sem 'url' e sem página aberta nesta sessão — informe url.")
        sel = _resolve_ref(selector, w.refs)
        if selector and sel is None:
            return ("ref desconhecido — rode action=snapshot de novo p/ renumerar os elementos "
                    f"(a página pode ter mudado): {selector}")
        out = _act_on_page(page, action, sel, text, screenshot, max_chars, w.refs)
        w.current_url = _current_url(page) or w.current_url
        return out

    try:
        return worker.call(lambda w: _op(w))
    except Exception as e:  # noqa: BLE001
        return f"(browse na sessão '{session_id}' falhou: {e})"


def browse(url: str | None = None, action: str = "read", selector: str | None = None,
           text: str | None = None, screenshot: str | None = None, max_chars: int = _MAX,
           *, session_id: str | None = None, dialog_policy: str | None = None) -> str:
    """action: read | open | snapshot | click | fill | screenshot | scroll | back | press | eval.

    snapshot/click/fill/screenshot/scroll/back/press/eval exigem Playwright. click/fill aceitam um
    ref [N] da última snapshot (resolvido por papel+nome acessível) OU um selector cru como fallback.

    `session_id` (opcional): quando informado, reusa o MESMO Chromium/página entre chamadas (login →
    navega → clica sem perder estado) via `browser_session.SESSIONS`. Sem ele, comportamento LEGADO:
    abre, age, fecha (cada chamada é um Chromium novo) — retrocompatível com chamadores existentes.
    """
    if url is not None:
        from okami.core.net_guard import BlockedURL, validate_public_url
        try:
            validate_public_url(url)                  # #6: vale tb p/ o goto do Playwright
        except BlockedURL as e:
            return f"(URL recusada: {e})"
    elif session_id is None:
        return "(browse: 'url' é obrigatório sem session_id)"

    if session_id is not None:
        return _browse_session(session_id, url, action, selector, text, screenshot, max_chars, dialog_policy)
    if url is None:                                    # não deveria chegar aqui (checado acima), defensivo
        return "(browse: 'url' é obrigatório)"
    return _browse_oneshot(url, action, selector, text, screenshot, max_chars)
