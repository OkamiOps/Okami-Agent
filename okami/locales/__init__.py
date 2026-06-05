"""Catálogos de tradução do Okami (i18n). Um módulo por locale, cada um expõe `MESSAGES: dict[str,str]`.

EN é o DEFAULT (fonte de verdade); PT é a tradução. Chaves namespaced por domínio:
`cli.*` · `chat.*` · `cmd.*` (descrições de slash command) · `cmd.cat.*` (rótulos de categoria) ·
`tui.*` · `err.*`. Veja okami/i18n.py para a resolução de locale e o helper `t()`.
"""
