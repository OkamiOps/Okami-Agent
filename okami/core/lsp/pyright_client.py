"""Cliente LSP mínimo sobre stdio (pesquisa #7 item 16) — fala JSON-RPC com pyright-langserver.

One-shot por arquivo: sobe o servidor, `initialize` → `textDocument/didOpen` → coleta o primeiro
`publishDiagnostics` daquele arquivo → `shutdown`/`exit`. Timeout curto (8s); estouro ou qualquer
falha → []. Binário ausente → [] (silencioso — fail-open, igual ao check_fn das tools). Nunca
levanta para fora.

Por que tão enxuto: pyright é caro de subir; rodamos só quando vale (item diagnostics.py decide).
Aqui só nos importa o contrato "dê-me a lista de diagnostics deste texto, ou [] se não der".
"""
from __future__ import annotations

import json
import subprocess  # noqa: S404 — invocamos um langserver local confiável, args fixos, sem shell
from pathlib import Path

_TIMEOUT_S = 8.0           # teto duro do one-shot; pyright frio pode demorar — 8s é o joelho
# Ordem importa: tentamos o canônico (pyright) antes do fork (basedpyright).
_CANDIDATES = ("pyright-langserver", "basedpyright-langserver")


def find_binary() -> str | None:
    """Caminho do langserver (pyright OU basedpyright), ou None se nenhum no PATH."""
    import shutil
    for name in _CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def _frame(payload: dict) -> bytes:
    """Embrulha um objeto JSON-RPC no enquadramento `Content-Length` do LSP."""
    body = json.dumps(payload).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _read_frames(stream, deadline: float):
    """Gera os payloads JSON-RPC que chegam no stdout até o deadline (parsing do enquadramento LSP).

    Tolerante: cabeçalho mal-formado ou EOF encerra a iteração em vez de levantar.
    """
    import time

    while True:
        if time.monotonic() > deadline:
            return
        # ----- cabeçalho: linhas até a vazia; só nos importa o Content-Length
        length = None
        while True:
            line = stream.readline()
            if not line:                                   # EOF
                return
            if isinstance(line, bytes):
                line = line.decode("ascii", "replace")
            line = line.strip()
            if line == "":                                 # fim do cabeçalho
                break
            if line.lower().startswith("content-length:"):
                try:
                    length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    length = None
        if not length:
            continue
        body = stream.read(length)
        if not body or len(body) < length:                 # truncado → desiste
            return
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        try:
            yield json.loads(body)
        except ValueError:
            continue


def _uri_for(workspace: Path, rel: str) -> str:
    return (Path(workspace) / rel).resolve().as_uri()


def diagnose(workspace, rel: str, text: str) -> list[dict]:
    """Diagnostics do pyright para `text` salvo como `rel` dentro de `workspace`.

    Retorna a lista de dicts `{message, severity, range, ...}` do LSP, ou [] se o binário não
    existe, dá timeout, ou qualquer coisa falha. NUNCA levanta.
    """
    binary = find_binary()
    if not binary:
        return []
    try:
        return _diagnose_inner(binary, workspace, rel, text)
    except Exception:  # noqa: BLE001 — fail-open: subprocess/IO/parse, tudo vira []
        return []


def _diagnose_inner(binary: str, workspace, rel: str, text: str) -> list[dict]:
    import threading
    import time

    deadline = time.monotonic() + _TIMEOUT_S
    uri = _uri_for(workspace, rel)
    proc = subprocess.Popen(  # noqa: S603 — binary vem de shutil.which (PATH), args fixos, sem shell
        [binary, "--stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    # Watchdog: readline/read são BLOQUEANTES — se o pyright travar sem emitir nada, o deadline-entre-
    # frames nunca dispara. Este timer MATA o processo no teto duro; o stdout vira EOF e _read_frames sai.
    watchdog = threading.Timer(_TIMEOUT_S, proc.kill)
    watchdog.daemon = True
    watchdog.start()
    try:
        root_uri = Path(workspace).resolve().as_uri()
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "processId": None, "rootUri": root_uri,
            "capabilities": {"textDocument": {"publishDiagnostics": {}}},
            # diagnósticos baseados em workspace ligados; sem checagem de libs de terceiros (rápido)
            "initializationOptions": {},
        }})
        _send(proc, {"jsonrpc": "2.0", "method": "initialized", "params": {}})
        _send(proc, {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": uri, "languageId": "python", "version": 1, "text": text},
        }})

        diagnostics: list[dict] = []
        for msg in _read_frames(proc.stdout, deadline):
            if (msg.get("method") == "textDocument/publishDiagnostics"
                    and msg.get("params", {}).get("uri") == uri):
                diagnostics = msg["params"].get("diagnostics") or []
                break                                      # 1º publish do NOSSO arquivo basta
        return diagnostics
    finally:
        watchdog.cancel()
        _shutdown(proc)


def _send(proc, payload: dict) -> None:
    try:
        proc.stdin.write(_frame(payload))
        proc.stdin.flush()
    except (BrokenPipeError, ValueError, OSError):          # servidor caiu no meio → segue p/ leitura
        pass


def _shutdown(proc) -> None:
    """Encerra o servidor educadamente; mata se travar. Não levanta."""
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 99, "method": "shutdown", "params": None})
        _send(proc, {"jsonrpc": "2.0", "method": "exit", "params": None})
    except Exception:  # noqa: BLE001
        pass
    try:
        proc.stdin and proc.stdin.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        proc.wait(timeout=1.0)
    except Exception:  # noqa: BLE001 — TimeoutExpired ou stub sem wait → mata
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
