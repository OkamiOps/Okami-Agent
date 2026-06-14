"""LSP semântico (pesquisa #7 item 16) — diagnostics-on-write DELTA via pyright.

Onde `code_lint` (item 6) pega só SINTAXE (compile/json/toml/yaml, stdlib), este módulo pega
o SEMÂNTICO: nome indefinido, import quebrado, atributo inexistente — via pyright-langserver
falando JSON-RPC sobre stdio. Tudo fail-open: sem .git, sem binário, sem .py → "" (silencioso).
Nunca levanta, nunca bloqueia a escrita — é só um aviso "talvez quebrei algo".
"""
from __future__ import annotations

from okami.core.lsp.diagnostics import lsp_delta

__all__ = ["lsp_delta"]
