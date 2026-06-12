"""Servir o Okami como servidor MCP (pesquisa #6 item 29, porta do mcp_serve do Hermes).

Expõe o que o agente SABE — sessões, histórico, memória — via MCP (JSON-RPC 2.0 sobre stdio), p/
Claude Code / Cursor / Codex consumirem. Read-only por padrão (não dá controle de execução a clientes
externos). O handler é PURO (dict→dict), testável sem stdio; `serve_stdio()` é o loop fino por cima.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROTOCOL = "2024-11-05"


def _text_result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


class OkamiMcpServer:
    def __init__(self, home, cfg=None):
        self.home = Path(home)
        self.cfg = cfg

    # ---------------------------------------------------------------- tools
    def _tool_specs(self) -> list[dict]:
        return [
            {"name": "sessions_list",
             "description": "Lista as conversas (chats) do agente Okami, com contadores.",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "session_read",
             "description": "Lê o transcript de uma conversa do Okami (papel + texto).",
             "inputSchema": {"type": "object",
                             "properties": {"chat_id": {"type": "string"},
                                            "limit": {"type": "integer"}},
                             "required": ["chat_id"]}},
            {"name": "session_search",
             "description": "Busca no histórico de TODAS as conversas do Okami (FTS5).",
             "inputSchema": {"type": "object",
                             "properties": {"query": {"type": "string"}},
                             "required": ["query"]}},
            {"name": "memory_recall",
             "description": "Recupera fatos/preferências da memória de longo prazo do Okami.",
             "inputSchema": {"type": "object",
                             "properties": {"query": {"type": "string"}},
                             "required": ["query"]}},
        ]

    def _call(self, name: str, args: dict) -> dict:
        if name == "sessions_list":
            from okami.gateway.sessions import TranscriptStore
            store = TranscriptStore(self.home)
            rows = [f"{cid}: {e.get('node_count', 0)} nós · título={e.get('title', '—')}"
                    for cid, e in store.load_store().items()]
            return _text_result("\n".join(rows) or "(nenhuma conversa)")
        if name == "session_read":
            from okami.gateway.sessions import TranscriptStore
            store = TranscriptStore(self.home)
            try:
                limit = int(args.get("limit") or 50)
            except (TypeError, ValueError):
                limit = 50
            nodes = store.read(str(args.get("chat_id", "")), limit=limit)
            lines = [f"{n.get('role', '?')}: {n.get('text', '')}" for n in nodes if n.get("role")]
            return _text_result("\n".join(lines) or "(conversa vazia ou inexistente)")
        if name == "session_search":
            from okami.memory.session_search import search_sessions
            hits = search_sessions(self.home, str(args.get("query", "")), 10)
            lines = [f"[sessão {h['chat_id']} · {h.get('role', '')}] {h.get('snippet') or h['text'][:160]}"
                     for h in hits]
            return _text_result("\n".join(lines) or "(nada no histórico)")
        if name == "memory_recall":
            try:
                from okami.memory import open_memory
                mem = open_memory(self.home, backend=(self.cfg.memory.get("backend", "sqlite-fts5")
                                                      if self.cfg else "sqlite-fts5"))
                items = mem.recall(str(args.get("query", "")), 5)
                out = "\n".join(getattr(i, "text", str(i)) for i in items) or "(nada na memória)"
                mem.close()
                return _text_result(out)
            except Exception as e:  # noqa: BLE001
                return {"content": [{"type": "text", "text": f"memória indisponível: {e}"}], "isError": True}
        return {"content": [{"type": "text", "text": f"tool desconhecida: {name}"}], "isError": True}

    # ---------------------------------------------------------------- JSON-RPC
    def handle(self, req: dict) -> dict | None:
        """Processa UMA requisição JSON-RPC. Retorna a resposta (dict) ou None p/ notificação (sem id)."""
        method = req.get("method", "")
        rid = req.get("id")
        if rid is None:                               # notificação → sem resposta
            return None
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": _PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "okami", "version": _okami_version()}}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": rid, "result": {"tools": self._tool_specs()}}
        if method == "tools/call":
            params = req.get("params") or {}
            try:
                result = self._call(params.get("name", ""), params.get("arguments") or {})
            except Exception as e:  # noqa: BLE001 — uma tool nunca derruba o servidor
                result = {"content": [{"type": "text", "text": f"erro: {e}"}], "isError": True}
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": f"method not found: {method}"}}

    def serve_stdio(self, *, stdin=None, stdout=None) -> None:  # pragma: no cover — loop de I/O
        """Loop MCP stdio: lê JSON-RPC por linha do stdin, escreve respostas no stdout."""
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except ValueError:
                continue
            resp = self.handle(req)
            if resp is not None:
                stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                stdout.flush()


def _okami_version() -> str:
    try:
        from okami import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return "0"
