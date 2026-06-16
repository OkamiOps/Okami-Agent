"""Subsistema LSP do Okami (#17, port do Hermes agent/lsp).

O Okami age como CLIENTE LSP: spawna language servers externos (pyright/gopls/typescript-language-server…)
e consome os `textDocument/publishDiagnostics` p/ enriquecer o write/edit com diagnostics SEMÂNTICOS reais
(filtro delta: só os erros INTRODUZIDOS pela edição atual). Gateado em repositório git + binário disponível.

Camadas PURAS (testáveis offline): protocol (framing JSON-RPC), range_shift (remap de linha diff-aware),
reporter (formatação), workspace (resolução de raiz git-gateada), servers (catálogo). O cliente async +
spawn de subprocesso é a parte de integração.
"""
from __future__ import annotations

from okami.lsp import protocol, range_shift, reporter, servers, workspace

__all__ = ["protocol", "range_shift", "reporter", "servers", "workspace"]
