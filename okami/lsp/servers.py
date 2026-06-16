"""Registro de language servers suportados (#17, inspirado no Hermes agent/lsp/servers.py).

Cada servidor: id, binário, extensões que cobre, marcadores de raiz do projeto, dica de install. O LSP
spawna o servidor (pyright/gopls/…) e consome os `publishDiagnostics` p/ enriquecer o write/edit com
diagnostics SEMÂNTICOS reais. Aqui mora só o catálogo (puro/testável); o spawn vive no client.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LspServer:
    id: str
    binary: str
    args: tuple = ()
    extensions: tuple = ()                 # ".py", ".ts", …
    root_markers: tuple = ()               # pyproject.toml, Cargo.toml, …
    install_hint: str = ""                 # como o dono instala (não auto-instalamos sem consentir)
    languages: tuple = ()
    excludes: tuple = field(default_factory=tuple)   # marcador que GATEIA off (ex.: deno.json p/ ts)


LSP_SERVERS: tuple[LspServer, ...] = (
    LspServer("pyright", "pyright-langserver", ("--stdio",), (".py", ".pyi"),
              ("pyproject.toml", "setup.cfg", "setup.py", "requirements.txt"),
              "npm i -g pyright", ("python",)),
    LspServer("typescript", "typescript-language-server", ("--stdio",), (".ts", ".tsx", ".js", ".jsx"),
              ("tsconfig.json", "jsconfig.json", "package.json"),
              "npm i -g typescript typescript-language-server", ("typescript", "javascript"),
              excludes=("deno.json", "deno.jsonc")),
    LspServer("gopls", "gopls", (), (".go",), ("go.mod", "go.work"),
              "go install golang.org/x/tools/gopls@latest", ("go",)),
    LspServer("rust-analyzer", "rust-analyzer", (), (".rs",), ("Cargo.toml",),
              "rustup component add rust-analyzer", ("rust",)),
    LspServer("bash", "bash-language-server", ("start",), (".sh", ".bash"), (),
              "npm i -g bash-language-server", ("bash", "shell")),
    LspServer("clangd", "clangd", (), (".c", ".h", ".cpp", ".hpp", ".cc"),
              ("compile_commands.json", "CMakeLists.txt", "Makefile"),
              "instale o clangd pelo gerenciador do SO", ("c", "cpp")),
)

_BY_EXT: dict[str, LspServer] = {}
for _s in LSP_SERVERS:
    for _e in _s.extensions:
        _BY_EXT.setdefault(_e, _s)


def server_for_path(path: str) -> LspServer | None:
    """O language server que cobre a extensão de `path` (ou None)."""
    import os
    ext = os.path.splitext(path)[1].lower()
    return _BY_EXT.get(ext)


def server_by_id(server_id: str) -> LspServer | None:
    for s in LSP_SERVERS:
        if s.id == server_id:
            return s
    return None


def binary_available(server: LspServer) -> bool:
    """O binário do servidor está no PATH? (não instala — só reporta)."""
    import shutil
    return shutil.which(server.binary) is not None


def server_status() -> list[dict]:
    """Estado de cada servidor: {id, binary, installed, extensions, install_hint}. P/ `okami lsp status`."""
    return [{"id": s.id, "binary": s.binary, "installed": binary_available(s),
             "extensions": list(s.extensions), "install_hint": s.install_hint} for s in LSP_SERVERS]


__all__ = ["LspServer", "LSP_SERVERS", "server_for_path", "server_by_id", "binary_available", "server_status"]
