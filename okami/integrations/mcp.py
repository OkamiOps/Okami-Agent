"""Cliente MCP (Model Context Protocol) — stdio, síncrono, sem dependência extra.

Conecta a servidores MCP (filesystem, git, etc.), lista as tools deles e as embrulha como
tools NATIVAS do harness — então MCP passa pelas mesmas invariantes (validação de args,
anti-loop, go/no-go §12). Protocolo: JSON-RPC 2.0 newline-delimited sobre stdin/stdout.
Transporte HTTP/SSE entra depois.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import urllib.request
from typing import Callable

from okami.core.tools import Tool, ToolResult


class McpError(Exception):
    pass


def _parse_jsonrpc(raw: str) -> dict:
    """Parseia uma resposta JSON-RPC, seja JSON puro ou SSE (text/event-stream)."""
    raw = raw.strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        msg = json.loads(raw)
    else:                                            # SSE: pega o último "data:"
        datas = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
        msg = json.loads(datas[-1]) if datas else {}
    if "error" in msg:
        raise McpError(str(msg["error"]))
    return msg.get("result", {})


class McpHttpClient:
    """Cliente MCP sobre HTTP (JSON-RPC POST, aceita resposta JSON ou SSE). Mesma interface do stdio."""

    def __init__(self, url: str, headers: dict | None = None, timeout: float = 30.0):
        self.url, self.headers, self.timeout = url, headers or {}, timeout
        self._id, self._session, self.tools = 0, None, []

    def _post(self, method: str, params: dict | None = None, notify: bool = False) -> dict:
        self._id += 1
        body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            body["id"] = self._id
        req = urllib.request.Request(self.url, data=json.dumps(body).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        for k, v in self.headers.items():
            req.add_header(k, v)
        if self._session:
            req.add_header("Mcp-Session-Id", self._session)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310
            sid = r.headers.get("Mcp-Session-Id")
            if sid:
                self._session = sid
            raw = r.read().decode("utf-8", "ignore")
        return {} if notify else _parse_jsonrpc(raw)

    def start(self) -> list[dict]:
        self._post("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                  "clientInfo": {"name": "okami", "version": "0"}})
        self._post("notifications/initialized", notify=True)
        self.tools = self._post("tools/list", {}).get("tools", [])
        return self.tools

    def call_tool(self, name: str, arguments: dict) -> tuple[bool, str]:
        res = self._post("tools/call", {"name": name, "arguments": arguments})
        parts = [c.get("text", "") if c.get("type") == "text" else json.dumps(c)
                 for c in res.get("content", [])]
        return (not res.get("isError", False)), ("\n".join(p for p in parts if p) or "(ok)")

    def close(self) -> None:
        pass


class McpStdioClient:
    def __init__(self, command: str, args=None, env=None, cwd=None, timeout: float = 30.0):
        self.cmd = [command, *(args or [])]
        self.env = env
        self.cwd = cwd
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._q: queue.Queue = queue.Queue()
        self.tools: list[dict] = []

    def start(self) -> list[dict]:
        # Servidor MCP é processo de TERCEIRO → NÃO vaza chaves/tokens do ambiente (mesma
        # sanitização do run_shell). Env extra explícito (self.env do config) é allowlist opt-in.
        from okami.core.tools import sanitized_env
        full_env = {**sanitized_env(), **(self.env or {})}
        self.proc = subprocess.Popen(
            self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1, env=full_env, cwd=self.cwd,
        )
        threading.Thread(target=self._read_loop, daemon=True).start()
        self._request("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "okami", "version": "0.0.1"},
        })
        self._notify("notifications/initialized")
        self.tools = self._request("tools/list", {}).get("tools", [])
        return self.tools

    def _read_loop(self) -> None:
        try:
            for line in self.proc.stdout:  # type: ignore[union-attr]
                self._q.put(line)
        finally:
            self._q.put(None)  # EOF

    def _send(self, msg: dict) -> None:
        self.proc.stdin.write(json.dumps(msg) + "\n")  # type: ignore[union-attr]
        self.proc.stdin.flush()  # type: ignore[union-attr]

    def _notify(self, method: str, params=None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _request(self, method: str, params: dict) -> dict:
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                line = self._q.get(timeout=max(0.05, deadline - time.time()))
            except queue.Empty:
                break
            if line is None:
                raise McpError(f"servidor MCP fechou (method={method})")
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == rid:
                if "error" in msg:
                    raise McpError(str(msg["error"]))
                return msg.get("result", {})
            # senão: notificação/log → ignora
        raise McpError(f"timeout no MCP (method={method})")

    def call_tool(self, name: str, arguments: dict) -> tuple[bool, str]:
        res = self._request("tools/call", {"name": name, "arguments": arguments})
        parts = []
        for c in res.get("content", []):
            parts.append(c.get("text", "") if c.get("type") == "text" else json.dumps(c))
        text = "\n".join(p for p in parts if p) or "(ok)"
        return (not res.get("isError", False)), text

    def close(self) -> None:
        if not self.proc:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self.proc.kill()


class McpTool(Tool):
    """Embrulha uma tool de um servidor MCP como Tool nativa do harness."""

    def __init__(self, client: McpStdioClient, spec: dict, prefix: str = ""):
        self._client = client
        self._remote = spec.get("name", "")
        self.name = f"{prefix}{self._remote}"
        self.description = (spec.get("description") or f"tool MCP {self._remote}")[:200]
        schema = spec.get("inputSchema") or {}
        props = schema.get("properties") or {}
        self.args_schema = {k: (v.get("description") or v.get("type") or "") for k, v in props.items()}
        self.required = tuple(schema.get("required") or ())

    def run(self, args, ctx):
        try:
            ok, text = self._client.call_tool(self._remote, args)
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"erro MCP {self.name}: {e}")
        return ToolResult(ok, text, effect=True)


def load_mcp_tools(servers: dict, emit: Callable[[str], None] = lambda m: None):
    """Inicia os servidores MCP configurados e retorna (tools_por_nome, clients)."""
    tools: dict[str, Tool] = {}
    clients: list[McpStdioClient] = []
    for name, conf in (servers or {}).items():
        if conf.get("disabled"):
            continue
        try:
            if conf.get("url"):                      # transporte HTTP/SSE (§12)
                client = McpHttpClient(conf["url"], conf.get("headers"), conf.get("timeout", 30))
            else:
                client = McpStdioClient(
                    conf["command"], conf.get("args"), conf.get("env"),
                    conf.get("cwd"), conf.get("timeout", 30),
                )
            specs = client.start()
            clients.append(client)
            for spec in specs:
                t = McpTool(client, spec, prefix=f"{name}__")
                tools[t.name] = t
            emit(f"MCP '{name}': {len(specs)} tool(s)")
        except Exception as e:  # noqa: BLE001 — um servidor ruim não derruba os outros
            emit(f"MCP '{name}' falhou: {e}")
    return tools, clients
