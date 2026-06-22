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

import re

_MAX = 6000

# Roles da árvore de acessibilidade que valem um [N] clicável/preenchível.
_INTERACTIVE_ROLES = frozenset({
    "link", "button", "textbox", "searchbox", "combobox", "checkbox",
    "radio", "switch", "menuitem", "tab", "option", "slider", "spinbutton",
})

# Mapa ref->elemento da ÚLTIMA snapshot, p/ resolver [N] em click/fill. Persistente no módulo:
# sobrevive entre chamadas de browse() dentro do mesmo processo (a "page persistente" da sessão).
_LAST_REFS: dict[int, dict] = {}


def _strip_html(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def fetch(url: str, max_chars: int = _MAX) -> str:
    from okami.core.net_guard import BROWSER_HEADERS, BlockedURL, guarded_urlopen
    try:
        with guarded_urlopen(url, timeout=20, headers=dict(BROWSER_HEADERS)) as r:  # #6 anti-SSRF · UA navegador real
            return _strip_html(r.read(300_000).decode("utf-8", "ignore"))[:max_chars]
    except BlockedURL as e:
        return f"(URL recusada: {e})"
    except Exception as e:  # noqa: BLE001
        return f"(erro ao buscar {url}: {e})"


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


def _snapshot(page, max_chars: int) -> str:
    """Numera os interativos [N], popula _LAST_REFS e devolve o mapa legível + texto da página."""
    _LAST_REFS.clear()
    tree = page.accessibility.snapshot()
    items: list[dict] = []
    if tree:
        _walk_interactive(tree, items)
    linhas = []
    for i, el in enumerate(items, start=1):
        _LAST_REFS[i] = el
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


def _resolve_ref(selector: str | None) -> str | None:
    """Se `selector` for um ref [N] da última snapshot, devolve o seletor real; senão devolve-o
    intacto (fallback CSS/seletor cru). Ref desconhecido vira None (deixa o chamador avisar)."""
    if not selector:
        return selector
    m = re.fullmatch(r"\s*\[(\d+)\]\s*", selector)
    if not m:
        return selector                                # não é ref → passa direto (compat)
    el = _LAST_REFS.get(int(m.group(1)))
    if el is None:
        return None                                    # ref expirado/inexistente
    return _ref_selector(el)


def browse(url: str, action: str = "read", selector: str | None = None, text: str | None = None,
           screenshot: str | None = None, max_chars: int = _MAX) -> str:
    """action: read | snapshot | click | fill | screenshot.

    snapshot/click/fill/screenshot exigem Playwright. click/fill aceitam um ref [N] da última
    snapshot (resolvido por papel+nome acessível) OU um selector cru como fallback.
    """
    from okami.core.net_guard import BlockedURL, validate_public_url
    try:
        validate_public_url(url)                      # #6: vale tb p/ o goto do Playwright
    except BlockedURL as e:
        return f"(URL recusada: {e})"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return fetch(url, max_chars)                  # sem Playwright → read-only (silencioso)
    from okami.home import okami_home
    profile = okami_home() / "browser_profile"        # sessão persistente p/ sites logados
    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        # contexto persistente = cookies/login sobrevivem entre chamadas (no lugar de launch()+new_page())
        context = p.chromium.launch_persistent_context(user_data_dir=str(profile))
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
