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
import re
import subprocess
import threading
import time
import urllib.request
from typing import Callable

from okami.core.tools import Tool, ToolResult


class McpError(Exception):
    pass


# Manifesto de CAPABILITY de tool MCP (#8) — classifica o que cada tool de terceiro pode fazer.
_MCP_CAPS = [
    ("write", re.compile(r"writ|creat|delet|updat|edit|\bput\b|\bpost\b|mov|renam|insert|upload|commit|push|set[_-]", re.I)),
    ("shell", re.compile(r"shell|exec|\brun\b|command|bash|terminal|spawn", re.I)),
    ("network", re.compile(r"fetch|http|\burl\b|\bweb\b|search|brows|request|download|crawl|\bsend\b", re.I)),
    ("secret-access", re.compile(r"secret|token|credential|api[_-]?key|password|\bauth", re.I)),
    ("read", re.compile(r"read|\bget\b|list|search|find|fetch|show|describ|query", re.I)),
]
DANGEROUS_CAPS = frozenset({"write", "shell", "network", "secret-access", "external-side-effect"})


def infer_capabilities(spec: dict) -> set[str]:
    """Capabilities de uma tool MCP por nome+descrição (read/write/network/shell/secret-access/…)."""
    text = (str(spec.get("name", "")) + " " + str(spec.get("description") or "")).lower()
    caps = {cap for cap, rx in _MCP_CAPS if rx.search(text)}
    if caps & {"network", "write"}:
        caps.add("external-side-effect")
    return caps or {"read"}


def servers_of(mcp_conf) -> dict:
    """Normaliza o bloco `mcp:` → {nome: conf}. Canônico é `mcp.servers.<n>`; aceita flat `mcp.<n>` (compat).

    Antes, lint/policy iteravam `cfg.mcp.items()` direto → pegavam ('servers', {...}) em vez de cada
    servidor → um MCP `trusted` dentro de mcp.servers passava batido (#P1)."""
    mcp = mcp_conf if isinstance(mcp_conf, dict) else {}
    srv = mcp.get("servers")
    if isinstance(srv, dict):
        return srv
    return {k: v for k, v in mcp.items() if isinstance(v, dict) and k != "servers"}


_TRUST_LEVELS = ("untrusted", "reviewed", "trusted")


def _trust_of(conf: dict) -> str:
    """Nível de confiança do servidor (#11): untrusted (default) | reviewed | trusted.

    `trusted: true` (legado) → 'trusted'. Desconhecido → 'untrusted' (fail-safe)."""
    lvl = str(conf.get("trust", "")).lower().strip()
    if lvl in _TRUST_LEVELS:
        return lvl
    return "trusted" if conf.get("trusted") else "untrusted"


def _tool_manifest(conf: dict, tname: str):
    """(capabilities|None, approval_policy, tem_manifesto?) p/ a tool `tname` do servidor.

    Precedência: entrada por-tool em `tools.<nome>` > override por-servidor `capabilities` > inferência."""
    entry = (conf.get("tools") or {}).get(tname) or {}
    server_caps = conf.get("capabilities")                  # override legado, vale p/ o servidor todo
    declared = entry.get("capabilities", server_caps)
    caps = set(declared) if declared is not None else None  # None → McpTool infere
    policy = str(entry.get("approval", "auto")).lower()
    has_manifest = bool(entry) or server_caps is not None
    return caps, policy, has_manifest


def _mcp_url_ok(url: str) -> bool:
    """HTTPS, ou host LOCAL (loopback/.local) — senão é plaintext / servidor arbitrário (recusa por padrão)."""
    from urllib.parse import urlparse
    u = urlparse(url)
    if u.scheme == "https":
        return True
    host = (u.hostname or "").lower()
    return u.scheme == "http" and (host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".local"))


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
    def __init__(self, command: str, args=None, env=None, cwd=None, timeout: float = 30.0,
                 env_passthrough=None):
        self.cmd = [command, *(args or [])]
        self.env = env
        # allowlist de NOMES de env var a repassar do ambiente (ex.: ELEVENLABS_API_KEY do ~/.okami/.env)
        # SEM versionar o token. O resto do ambiente continua sanitizado.
        self.env_passthrough = list(env_passthrough or [])
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
        base = sanitized_env()
        for nm in self.env_passthrough:                 # repassa só os segredos explicitamente liberados
            if nm in os.environ:
                base[nm] = os.environ[nm]
        full_env = {**base, **(self.env or {})}
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

    def __init__(self, client: McpStdioClient, spec: dict, prefix: str = "", *,
                 capabilities=None, trusted: bool = False, approval_policy: str = "auto",
                 unverified: bool = False):
        self._client = client
        self._remote = spec.get("name", "")
        self.name = f"{prefix}{self._remote}"
        self.description = (spec.get("description") or f"tool MCP {self._remote}")[:200]
        schema = spec.get("inputSchema") or {}
        props = schema.get("properties") or {}
        self.args_schema = {k: (v.get("description") or v.get("type") or "") for k, v in props.items()}
        self.required = tuple(schema.get("required") or ())
        self.capabilities = set(capabilities) if capabilities is not None else infer_capabilities(spec)
        self.trusted = trusted              # servidor de confiança → não força go/no-go por capability (#8)
        # política de aprovação do MANIFESTO (#11): auto (gate por capability) | never (liberada) | always.
        self.approval_policy = approval_policy
        # #11: servidor UNTRUSTED + tool SEM manifesto → não confio na inferência por nome ("read" bonitinho).
        self.unverified = unverified

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
        url = conf.get("url")
        if url and not _mcp_url_ok(url) and not conf.get("insecure"):   # #8: HTTPS/local-only por padrão
            emit(f"⚠ MCP '{name}' RECUSADO: {url} não é HTTPS nem local — use https:// (ou insecure: true, perigoso).")
            continue
        for hk, hv in (conf.get("headers") or {}).items():            # #8/#6: header com segredo literal
            if isinstance(hv, str) and len(hv) > 8 and not hv.strip().startswith("${"):
                emit(f"⚠ MCP '{name}' header {hk}: parece SEGREDO em texto — use ${{ENV_VAR}} (não versione token).")
        trust = _trust_of(conf)                      # #11: untrusted (default) | reviewed | trusted
        trusted = trust == "trusted"
        from okami.core.envref import resolve_env, resolve_env_map
        try:
            if url:                                  # transporte HTTP/SSE (§12)
                # resolve ${ENV} nos headers — antes o literal `${TOKEN}` ia cru pro servidor.
                client = McpHttpClient(resolve_env(url), resolve_env_map(conf.get("headers")),
                                       conf.get("timeout", 30))
            else:
                client = McpStdioClient(
                    conf["command"], conf.get("args"), resolve_env_map(conf.get("env")),
                    conf.get("cwd"), conf.get("timeout", 30),
                    env_passthrough=conf.get("env_passthrough"),
                )
            specs = client.start()
            clients.append(client)
            unverified_names = []
            for spec in specs:
                caps, policy, has_manifest = _tool_manifest(conf, spec.get("name", ""))
                # #11: untrusted + sem manifesto → não confia na inferência por nome → exige go/no-go.
                unverified = (trust == "untrusted") and not has_manifest
                if unverified:
                    unverified_names.append(spec.get("name", ""))
                t = McpTool(client, spec, prefix=f"{name}__", capabilities=caps, trusted=trusted,
                            approval_policy=policy, unverified=unverified)
                tools[t.name] = t
            danger = sorted({c for t in tools.values() if t.name.startswith(f"{name}__")
                             for c in getattr(t, "capabilities", set()) if c in DANGEROUS_CAPS})
            extra = f" · trust={trust}"
            if danger:
                extra += f" · capabilities perigosas: {', '.join(danger)}"
            if unverified_names:
                extra += f" · {len(unverified_names)} não-revisada(s) → go/no-go"
            emit(f"MCP '{name}': {len(specs)} tool(s)" + extra)
        except Exception as e:  # noqa: BLE001 — um servidor ruim não derruba os outros
            emit(f"MCP '{name}' falhou: {e}")
    return tools, clients
