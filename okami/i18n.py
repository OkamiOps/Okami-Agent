"""i18n leve do Okami — `t(key)` resolve a string no locale atual. **EN é o default; PT disponível.**

Sem dependência externa nem build step (gettext/.mo): os catálogos são dicts Python em
`okami/locales/{en,pt}.py` com chaves NAMESPACED por domínio — ex.: `"cli.doctor.help"`,
`"chat.cancelling"`. Resolução do locale (1ª que casar):

    1. set_lang() em runtime (CLI `--lang`, testes)
    2. env OKAMI_LANG (ex.: `pt`, `pt_BR`, `en`)
    3. config `lang:` no okami.yaml
    4. DEFAULT_LANG ('en')

Fallback de uma chave ausente: locale atual → EN → a própria key (visível e debugável, nunca quebra).
Interpolação por `str.format` (`t("x.greet", name=...)` → `"Hi {name}"`).
"""

from __future__ import annotations

import os
from functools import lru_cache

DEFAULT_LANG = "en"
SUPPORTED = ("en", "pt")

_override: str | None = None      # set_lang() — vence tudo (CLI --lang / testes)
_resolved: str | None = None      # cache do locale efetivo (env/config lidos 1x por processo)


def _norm(lang: str | None) -> str | None:
    """'pt_BR'/'PT-br'/'pt' → 'pt'; só devolve se suportado, senão None."""
    code = (lang or "").lower().replace("-", "_").split("_")[0].strip()
    return code if code in SUPPORTED else None


def set_lang(lang: str | None) -> None:
    """Fixa o locale em runtime (vence env/config). `None` limpa o override (volta a resolver)."""
    global _override, _resolved
    _override = _norm(lang)
    _resolved = None                                  # força re-resolver na próxima chamada


def current_lang() -> str:
    """Locale efetivo (override → env → config → default). Resolvido 1x e cacheado por processo."""
    global _resolved
    if _override:
        return _override
    if _resolved:
        return _resolved
    lang = _norm(os.getenv("OKAMI_LANG"))
    if not lang:
        try:                                          # config `lang:` (best-effort — nunca lança no t())
            from okami.config import load_raw
            raw, _ = load_raw()
            lang = _norm(str((raw or {}).get("lang") or ""))
        except Exception:  # noqa: BLE001
            lang = None
    _resolved = lang or DEFAULT_LANG
    return _resolved


@lru_cache(maxsize=None)
def _catalog(lang: str) -> dict:
    try:
        mod = __import__(f"okami.locales.{lang}", fromlist=["MESSAGES"])
        cat = getattr(mod, "MESSAGES", {})
        return cat if isinstance(cat, dict) else {}
    except Exception:  # noqa: BLE001 — catálogo ausente/quebrado → vazio (cai no fallback)
        return {}


def t(key: str, /, _default: str | None = None, **kwargs) -> str:
    """Traduz `key` no locale atual. Ordem: catálogo do locale → catálogo EN → `_default` → a própria key.

    `_default` deixa o INGLÊS inline no código como fonte (padrão gettext: o texto-fonte é o EN); só o PT
    precisa ir pro catálogo. Sem `_default`, uma key ausente cai na própria key (visível/debugável).
    Interpola via str.format(**kwargs)."""
    lang = current_lang()
    s = _catalog(lang).get(key)
    if s is None and lang != DEFAULT_LANG:
        s = _catalog(DEFAULT_LANG).get(key)
    if s is None:
        s = _default if _default is not None else key
    try:
        return s.format(**kwargs) if kwargs else s
    except (KeyError, IndexError, ValueError):        # placeholder solto não pode derrubar a saída
        return s


def missing_keys(lang: str) -> list[str]:
    """Chaves que existem em EN mas faltam em `lang` (p/ teste de cobertura de tradução)."""
    base = set(_catalog(DEFAULT_LANG))
    return sorted(base - set(_catalog(lang)))
