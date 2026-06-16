"""Mock LSP server (stdlib) p/ testar o cliente persistente sem pyright. Fala o framing Content-Length:
- responde `initialize` com um result;
- a cada `didOpen`/`didChange`, publica diagnostics: 1 ERROR se o texto contém 'BUG_SENTINEL', senão 0.
Roda como `python tests/lsp_mock_server.py`.
"""
from __future__ import annotations

import json
import sys


def _read_message(stdin):
    length = None
    while True:
        line = stdin.readline()
        if not line:
            return None
        line = line.decode("ascii", "replace").strip() if isinstance(line, bytes) else line.strip()
        if line == "":
            break
        if line.lower().startswith("content-length:"):
            try:
                length = int(line.split(":", 1)[1].strip())
            except ValueError:
                length = None
    if not length:
        return {}
    body = stdin.read(length)
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    try:
        return json.loads(body)
    except ValueError:
        return {}


def _send(stdout, payload):
    body = json.dumps(payload).encode("utf-8")
    stdout.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    stdout.flush()


def _publish(stdout, uri, text):
    diags = []
    if "BUG_SENTINEL" in (text or ""):
        diags = [{"severity": 1, "message": 'erro de mentira', "code": "MOCK001", "source": "mock",
                  "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}}}]
    _send(stdout, {"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                   "params": {"uri": uri, "diagnostics": diags}})


def main():
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        msg = _read_message(stdin)
        if msg is None:
            return
        method = msg.get("method")
        if method == "initialize":
            _send(stdout, {"jsonrpc": "2.0", "id": msg.get("id"), "result": {"capabilities": {}}})
        elif method in ("textDocument/didOpen", "textDocument/didChange"):
            params = msg.get("params") or {}
            td = params.get("textDocument") or {}
            uri = td.get("uri")
            if method == "textDocument/didOpen":
                text = td.get("text", "")
            else:
                changes = params.get("contentChanges") or [{}]
                text = changes[-1].get("text", "")
            _publish(stdout, uri, text)
        elif method == "exit":
            return


if __name__ == "__main__":
    main()
